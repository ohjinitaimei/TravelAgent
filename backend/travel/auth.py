"""Local accounts, opaque sessions and request identity. No public registration."""
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from threading import BoundedSemaphore
import time
from uuid import uuid4
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from travel.provider import TravelFailure
from travel.schemas import AuthStatus, AuthUser, ErrorResponse, LoginRequest, LoginResponse

COOKIE='travelagent_session'
PREFIX='/api/v1/travel'
TOKEN=re.compile(r'^[A-Za-z0-9_-]{43}$')
PASSWORD_SLOTS=BoundedSemaphore(2)
cookie_security=APIKeyCookie(name=COOKIE,auto_error=False)
bearer_security=HTTPBearer(auto_error=False)


def username(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,39}',value):
        raise ValueError('账号须为 3–40 位字母、数字、点、下划线或连字符')
    return value.lower()


def password_hash(password):
    if not 15<=len(password)<=128:
        raise ValueError('密码须为 15–128 个字符')
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode('utf-8'),salt=salt,n=2**17,r=8,p=1,maxmem=256*1024*1024,dklen=32)
    return f'scrypt$131072$8$1${salt.hex()}${digest.hex()}'


def password_matches(password,encoded):
    try:
        algorithm,n,r,p,salt,expected=encoded.split('$')
        if (algorithm,n,r,p)!=('scrypt','131072','8','1') or len(salt)!=32 or len(expected)!=64: return False
        actual=hashlib.scrypt(password.encode('utf-8'),salt=bytes.fromhex(salt),n=2**17,r=8,p=1,maxmem=256*1024*1024,dklen=32)
        return hmac.compare_digest(actual,bytes.fromhex(expected))
    except (ValueError,TypeError): return False


@lru_cache(maxsize=1)
def dummy_password():
    return password_hash(secrets.token_urlsafe(24))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf(token):
    return hmac.new(token.encode(),b'travelagent:csrf:v1',hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Identity:
    user: AuthUser
    token: str | None = None
    kind: str = 'local'
    expires_at: float | None = None


class AuthService:
    def __init__(self,store):
        self.store=store
        self.mode=os.getenv('TRAVEL_AUTH_MODE','local')
        self.secure=os.getenv('TRAVEL_COOKIE_SECURE','0')
        if self.mode not in {'local','session'} or self.secure not in {'0','1'}:
            raise ValueError('Invalid authentication configuration')
        self.secure=self.secure=='1'
        self.ttl=int(os.getenv('TRAVEL_SESSION_TTL','28800'))
        self.idle=int(os.getenv('TRAVEL_SESSION_IDLE_TTL','1800'))
        if not 300<=self.ttl<=86400 or not 60<=self.idle<=3600:
            raise ValueError('Invalid session lifetime')
        self.origins={v.strip().rstrip('/') for v in os.getenv('TRAVEL_CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',') if v.strip()}
        if self.mode=='session' and '*' in self.origins:
            raise ValueError('Session mode requires explicit CORS origins')
        with store.lock,store.db:
            store.db.executescript('''
              CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS auth_sessions (digest TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                expires_at REAL NOT NULL, last_seen REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS sessions_by_user ON auth_sessions(user_id);
              CREATE TABLE IF NOT EXISTS auth_attempts (key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
            ''')
        if self.mode=='session': dummy_password()

    def create_user(self,name,password):
        name=username(name)
        digest=password_hash(password)
        user=AuthUser(id=uuid4().hex,username=name)
        try:
            with self.store.lock,self.store.db:
                self.store.db.execute('INSERT INTO auth_users(id,username,password_hash) VALUES (?,?,?)',(user.id,name,digest))
        except sqlite3.IntegrityError:
            raise ValueError('账号已存在') from None
        return user

    def reset_password(self,name,password):
        digest=password_hash(password)
        with self.store.lock,self.store.db:
            row=self.store.db.execute('SELECT id FROM auth_users WHERE username=?',(username(name),)).fetchone()
            if not row: raise ValueError('账号不存在')
            self.store.db.execute('UPDATE auth_users SET password_hash=? WHERE id=?',(digest,row[0]))
            self.store.db.execute('DELETE FROM auth_sessions WHERE user_id=?',(row[0],))

    def disable_user(self,name):
        self.set_disabled(name,True)

    def enable_user(self,name):
        self.set_disabled(name,False)

    def set_disabled(self,name,disabled):
        with self.store.lock,self.store.db:
            row=self.store.db.execute('SELECT id FROM auth_users WHERE username=?',(username(name),)).fetchone()
            if not row: raise ValueError('账号不存在')
            self.store.db.execute('UPDATE auth_users SET disabled=? WHERE id=?',(int(disabled),row[0]))
            self.store.db.execute('DELETE FROM auth_sessions WHERE user_id=?',(row[0],))

    def limit_login(self,name,peer):
        now=time.time()
        keys=[(token_hash('user:'+name),10),(token_hash('peer:'+peer),60)]
        with self.store.lock,self.store.db:
            self.store.db.execute('DELETE FROM auth_attempts WHERE started<?',(now-300,))
            for key,limit in keys:
                row=self.store.db.execute('SELECT count FROM auth_attempts WHERE key=?',(key,)).fetchone()
                if row and row[0]>=limit:
                    raise TravelFailure('login_rate_limited','登录尝试过于频繁，请 5 分钟后重试',True,429)
            for key,_ in keys:
                self.store.db.execute('INSERT INTO auth_attempts VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now))

    def login(self,name,password,peer):
        if self.mode!='session': raise TravelFailure('auth_disabled','当前使用本地空间模式',status=409)
        name=username(name)
        self.limit_login(name,peer)
        if not PASSWORD_SLOTS.acquire(blocking=False):
            raise TravelFailure('auth_busy','登录服务繁忙，请稍后重试',True,429)
        try:
            with self.store.lock:
                row=self.store.db.execute('SELECT id,username,password_hash,disabled FROM auth_users WHERE username=?',(name,)).fetchone()
            valid=password_matches(password,row[2] if row else dummy_password())
            if not valid or not row or row[3]:
                raise TravelFailure('invalid_credentials','账号或密码不正确',status=401)
        finally: PASSWORD_SLOTS.release()
        token=secrets.token_urlsafe(32)
        now=time.time()
        with self.store.lock,self.store.db:
            # Recheck after hashing so password reset/disable cannot race login.
            current=self.store.db.execute('SELECT password_hash,disabled FROM auth_users WHERE id=?',(row[0],)).fetchone()
            if not current or current[1] or current[0]!=row[2]:
                raise TravelFailure('invalid_credentials','账号或密码不正确',status=401)
            self.store.db.execute('DELETE FROM auth_sessions WHERE expires_at<=? OR last_seen<=?',(now,now-self.idle))
            self.store.db.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)',(token_hash(token),row[0],now+self.ttl,now))
            self.store.db.execute('DELETE FROM auth_sessions WHERE user_id=? AND digest NOT IN (SELECT digest FROM auth_sessions WHERE user_id=? ORDER BY last_seen DESC,rowid DESC LIMIT 5)',(row[0],row[0]))
        return Identity(AuthUser(id=row[0],username=row[1]),token,'bearer',now+self.ttl)

    def resolve(self,token,kind):
        if not token or not TOKEN.fullmatch(token): return None
        now=time.time()
        with self.store.lock,self.store.db:
            row=self.store.db.execute('SELECT u.id,u.username,u.disabled,s.expires_at,s.last_seen FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.digest=?',(token_hash(token),)).fetchone()
            if not row: return None
            if row[2] or row[3]<=now or row[4]+self.idle<=now:
                self.store.db.execute('DELETE FROM auth_sessions WHERE digest=?',(token_hash(token),))
                return None
            if row[4]+60<=now: self.store.db.execute('UPDATE auth_sessions SET last_seen=? WHERE digest=?',(now,token_hash(token)))
            return Identity(AuthUser(id=row[0],username=row[1]),token,kind,row[3])

    def identify(self,request):
        if self.mode=='local': return Identity(AuthUser(id='local',username='本地空间'))
        header=request.headers.get('authorization')
        if header is not None:
            parts=header.split()
            if len(parts)!=2 or parts[0].lower()!='bearer': return None
            return self.resolve(parts[1],'bearer')
        return self.resolve(request.cookies.get(COOKIE),'cookie')

    def check_origin(self,request):
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or (origin and origin.rstrip('/') not in self.origins):
            raise TravelFailure('origin_rejected','请求来源未获授权',status=403)

    def revoke(self,token):
        if token:
            with self.store.lock,self.store.db:
                self.store.db.execute('DELETE FROM auth_sessions WHERE digest=?',(token_hash(token),))

    def status(self,identity=None):
        with self.store.lock:
            setup=self.store.db.execute('SELECT 1 FROM auth_users WHERE disabled=0 LIMIT 1').fetchone() is None
        return AuthStatus(mode=self.mode,authenticated=identity is not None,user=identity.user if identity else None,
            csrf_token=csrf(identity.token) if identity and identity.kind=='cookie' else None,
            expires_at=datetime.fromtimestamp(identity.expires_at,timezone.utc).isoformat() if identity and identity.expires_at else None,
            setup_required=self.mode=='session' and setup)


def require_user(request: Request,bearer: HTTPAuthorizationCredentials | None=Security(bearer_security),cookie: str | None=Security(cookie_security),
                 x_csrf_token: Annotated[str | None,Header(max_length=128,description='Cookie 会话的写操作须携带 auth/status 返回的 CSRF Token')]=None,
                 x_workspace_user: Annotated[str | None,Header(max_length=64,description='可选：校验页面绑定的用户 ID，防止跨标签页切换账号后误提交')]=None):
    service=request.app.state.auth
    identity=service.identify(request)
    if identity is None: raise TravelFailure('authentication_required','会话已失效，请重新登录',status=401)
    expected=request.headers.get('x-workspace-user')
    if expected and expected!=identity.user.id:
        raise TravelFailure('workspace_identity_changed','账号状态已变化，请重新登录后继续',status=409)
    if service.mode=='session' and request.method not in {'GET','HEAD','OPTIONS'}:
        service.check_origin(request)
        if identity.kind=='cookie' and not hmac.compare_digest(request.headers.get('x-csrf-token','').encode(),csrf(identity.token).encode()):
            raise TravelFailure('csrf_invalid','会话校验失败，请重新登录后重试',status=403)
    request.state.identity=identity
    return identity


def owner_id(request):
    return request.state.identity.user.id


router=APIRouter(prefix=PREFIX+'/auth',tags=['authentication'],responses={code:{'model':ErrorResponse} for code in (401,403,409,422,429,503)})


@router.get('/status',response_model=AuthStatus)
def auth_status(request: Request,response: Response):
    service=request.app.state.auth
    identity=service.identify(request)
    if not identity and request.cookies.get(COOKIE): response.delete_cookie(COOKIE,path=PREFIX)
    return service.status(identity)


@router.post('/login',response_model=LoginResponse)
def login(body: LoginRequest,request: Request,response: Response,
          x_travel_client: Annotated[str | None,Header(max_length=12,description='Cookie 登录须为 web；Bearer 登录可省略')]=None):
    service=request.app.state.auth
    service.check_origin(request)
    if body.transport=='cookie':
        if request.headers.get('x-travel-client')!='web':
            raise TravelFailure('client_header_required','请通过登录页面发起请求',status=403)
        if service.secure and request.url.scheme!='https':
            raise TravelFailure('https_required','当前会话配置要求 HTTPS 连接',status=503)
    identity=service.login(body.username,body.password.get_secret_value(),request.client.host if request.client else 'unknown')
    if body.transport=='cookie':
        service.revoke(request.cookies.get(COOKIE))
        identity=Identity(identity.user,identity.token,'cookie',identity.expires_at)
        response.set_cookie(COOKIE,identity.token,max_age=service.ttl,httponly=True,secure=service.secure,samesite='strict',path=PREFIX)
    return LoginResponse(**service.status(identity).model_dump(),access_token=identity.token if body.transport=='bearer' else None)


@router.post('/logout',response_model=AuthStatus)
def logout(request: Request,response: Response,identity=Depends(require_user)):
    request.app.state.auth.revoke(identity.token)
    if identity.kind=='cookie': response.delete_cookie(COOKIE,path=PREFIX)
    return request.app.state.auth.status()


def configure_auth(app):
    app.include_router(router)
    @app.middleware('http')
    async def private_responses(request,call_next):
        service=getattr(request.app.state,'auth',None)
        if service and service.mode=='session' and request.url.path.startswith('/api/') and not request.url.path.startswith(PREFIX+'/'):
            from fastapi.responses import JSONResponse
            response=JSONResponse(status_code=410,content={'error':{'code':'legacy_api_disabled','message':'账号模式仅提供统一旅行接口','retryable':False}})
        else: response=await call_next(request)
        if request.url.path.startswith(PREFIX):
            response.headers['Cache-Control']='no-store'
            response.headers.append('Vary','Cookie, Authorization')
        return response
