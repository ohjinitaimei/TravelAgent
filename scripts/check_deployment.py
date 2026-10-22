"""Read-only deployment preflight. Never print credentials or change a database."""
import argparse
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from dotenv import dotenv_values


def origin(value):
    if not isinstance(value,str) or any(c.isspace() or c in '{}*`"' for c in value):
        raise ValueError('HTTPS 来源不得包含空白、通配符或配置指令')
    try:
        parsed=urlsplit(value)
        valid=(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
               and parsed.path in ('','/') and not parsed.query and not parsed.fragment and parsed.port!=0)
    except ValueError:
        valid=False
    if not valid:
        raise ValueError('TRAVEL_SITE 必须是单个 HTTPS 来源，不得包含账号、路径或查询参数')
    return value.rstrip('/')


def validate(backend,gateway):
    for name,expected in {'TRAVEL_PRODUCTION':'1','TRAVEL_AUTH_MODE':'session','TRAVEL_COOKIE_SECURE':'1'}.items():
        if backend.get(name)!=expected:raise ValueError(name+' 不符合账号 HTTPS 部署要求')
    site=origin(gateway.get('TRAVEL_SITE',''))
    if backend.get('TRAVEL_CORS_ORIGINS','').rstrip('/')!=site:
        raise ValueError('后端来源须与网关 HTTPS 来源完全一致')
    http=urlsplit(gateway.get('TRAVEL_HTTP_SITE',''))
    if (http.scheme!='http' or http.hostname!=urlsplit(site).hostname or http.path not in ('','/')
        or http.username or http.query or http.fragment or http.port==0):raise ValueError('HTTP 跳转须指向同一域名')
    if gateway.get('TRAVEL_TLS',''):
        raise ValueError('正式部署须使用公开证书，不得设置 TRAVEL_TLS 测试覆盖')
    if gateway.get('TRAVEL_BIND','0.0.0.0') not in {'0.0.0.0','127.0.0.1'}:
        raise ValueError('TRAVEL_BIND 须为模板支持的 IPv4 监听地址')
    if any(k not in {'TRAVEL_SITE','TRAVEL_HTTP_SITE','TRAVEL_UPSTREAM','TRAVEL_WEB_ROOT','TRAVEL_CADDY_ADMIN','TRAVEL_BIND','TRAVEL_CADDY_DATA','TRAVEL_TLS'} for k in gateway):
        raise ValueError('网关文件只能包含公开网关配置，后端凭证须单独保存')
    for key,default in [('TRAVEL_UPSTREAM','127.0.0.1:8000'),('TRAVEL_CADDY_ADMIN','127.0.0.1:2019')]:
        match=re.fullmatch(r'127\.0\.0\.1:(\d{1,5})',gateway.get(key,default))
        if not match or not 1<=int(match[1])<=65535:raise ValueError(key+' 须绑定 IPv4 回环地址及有效端口')
    web=Path(gateway.get('TRAVEL_WEB_ROOT',''))
    db=Path(backend.get('TRAVEL_DB_PATH',''))
    if not web.is_absolute() or not (web/'index.html').is_file() or not (web/'assets').is_dir():
        raise ValueError('TRAVEL_WEB_ROOT 须指向已构建 dist 的绝对路径')
    if not db.is_absolute() or not db.parent.is_dir() or db.resolve().is_relative_to(web.resolve()):
        raise ValueError('数据库须使用静态目录之外的绝对路径，且父目录已存在')
    rate=Path(backend.get('TRAVEL_AMAP_RATE_DB_PATH') or db.parent/'amap-rate.sqlite3')
    if not rate.is_absolute() or not rate.parent.is_dir() or rate.resolve().is_relative_to(web.resolve()) or rate.resolve()==db.resolve():
        raise ValueError('节流状态须使用静态目录之外的独立绝对文件路径，且父目录已存在')
    for name,default,low,high in [('MIN_INTERVAL','1',.05,5),('MAX_WAIT','3',.1,5),('COOLDOWN','5',1,60)]:
        try:value=float(backend.get('TRAVEL_AMAP_'+name+'_SECONDS',default))
        except (ValueError,TypeError):raise ValueError('高德请求节流配置无效') from None
        if not math.isfinite(value) or not low<=value<=high:raise ValueError('高德请求节流配置无效')
    data=Path(gateway.get('TRAVEL_CADDY_DATA','/var/lib/caddy/travelagent'))
    if not data.is_absolute() or data.resolve().is_relative_to(web.resolve()):raise ValueError('证书存储须使用静态目录之外的绝对路径')
    forbidden={'.env','.git','backend','node_modules'}
    if any((web/name).exists() for name in forbidden):raise ValueError('静态目录包含非发布文件')
    # Check only configured server credentials; the JS browser key is public.
    secrets=[v for k,v in backend.items() if v and len(v)>=12 and
             (k.endswith(('API_KEY','SECURITY_CODE')) or k in {'AMAP_WEB_KEY','AMAP_KEY'})]
    for path in web.rglob('*'):
        if path.is_symlink():raise ValueError('静态目录不得包含符号链接')
        if path.is_file() and any(v.encode() in path.read_bytes() for v in secrets):
            raise ValueError('静态构建中发现后端凭证；请清理 VITE 配置后重新构建')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-env',type=Path,required=True)
    parser.add_argument('--gateway-env',type=Path,required=True)
    args=parser.parse_args()
    try:
        if not args.backend_env.is_file() or not args.gateway_env.is_file():raise ValueError('须显式指定两个已存在的配置文件')
        backend=dotenv_values(args.backend_env,interpolate=False)
        gateway=dotenv_values(args.gateway_env,interpolate=False)
        validate(backend,gateway)
        web=Path(gateway['TRAVEL_WEB_ROOT']).resolve()
        if any(p.resolve().is_relative_to(web) for p in (args.backend_env,args.gateway_env)):
            raise ValueError('配置文件不得存放在公开静态目录')
    except (OSError,ValueError) as error:
        parser.exit(1,'部署预检失败：'+str(error)+'\n')
    print('部署预检通过：HTTPS 来源、账号模式、数据目录、生产构建及凭证边界。未修改数据库。')


if __name__=='__main__':main()
