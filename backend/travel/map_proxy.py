"""Bounded, authenticated JS SDK gateway. Business queries use TravelTools."""
import asyncio
import hmac
import json
import logging
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from travel.auth import require_user, owner_id
from travel.provider import TravelFailure

PREFIX = '/api/v1/travel/_AMapService'
# No user-controlled destination, path prefix or Web service business endpoint.
UPSTREAMS = {
    'v3/log/init': 'https://restapi.amap.com/v3/log/init',
    'v4/map/styles': 'https://webapi.amap.com/v4/map/styles',
}
MAX_BYTES = 2 * 1024 * 1024
CALLBACK = re.compile(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', re.ASCII)
CONTENT_TYPES = {'application/json', 'application/javascript', 'application/x-javascript',
                 'text/javascript', 'application/octet-stream', 'application/x-protobuf', 'image/png'}


class SecretLogFilter(logging.Filter):
    """httpx's INFO request line includes its query; redact even at verbose levels."""
    def __init__(self, values):
        super().__init__()
        self.values = tuple(value for value in values if value)

    def filter(self, record):
        message = record.getMessage()
        for value in self.values:
            message = message.replace(value, '[REDACTED]')
        record.msg, record.args = message, ()
        return True


class MapProxy:
    def __init__(self):
        self.key = os.getenv('AMAP_JS_KEY', '').strip()
        self.code = os.getenv('AMAP_JS_SECURITY_CODE', '').strip()
        self.log_filter = SecretLogFilter((self.key, self.code))
        logging.getLogger('httpx').addFilter(self.log_filter)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5, pool=2),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            follow_redirects=False, trust_env=False)

    async def close(self):
        await self.client.aclose()
        logging.getLogger('httpx').removeFilter(self.log_filter)

    def parameters(self, request, path):
        if path not in UPSTREAMS:
            raise TravelFailure('map_path_rejected', '地图代理不支持此接口', status=404)
        if not self.key or not self.code:
            raise TravelFailure('map_proxy_not_configured', '浏览器地图代理尚未配置', status=503)
        if len(request.scope.get('query_string', b'')) > 4096:
            raise TravelFailure('map_query_rejected', '地图请求参数过长', status=422)
        params = request.query_params.multi_items()
        names = [name.lower() for name, _ in params]
        if len(params) > 32 or len(set(names)) != len(names) or 'jscode' in names:
            raise TravelFailure('map_query_rejected', '地图请求参数无效', status=422)
        values = dict(params)
        if not hmac.compare_digest(values.get('key', '').encode(), self.key.encode()):
            raise TravelFailure('map_key_rejected', '浏览器地图 Key 不匹配', status=403)
        if any(name.lower() == 'callback' and (name != 'callback' or len(value) > 128 or not CALLBACK.fullmatch(value)) for name, value in params):
            raise TravelFailure('map_query_rejected', '地图回调参数无效', status=422)
        values['jscode'] = self.code
        return values

    async def fetch(self, path, params, referer=None):
        # Never forward Cookie, Authorization, Origin, user-selected Host or URL.
        headers = {'Accept': '*/*', 'Accept-Encoding': 'identity'}
        if referer:
            headers['Referer'] = referer
        try:
            async with asyncio.timeout(12):
                async with self.client.stream('GET', UPSTREAMS[path], params=params, headers=headers) as response:
                    if response.status_code != 200:
                        raise TravelFailure('map_upstream_rejected', '地图服务暂不可用', True)
                    content_type = response.headers.get('content-type', '').split(';')[0].lower().strip()
                    if content_type not in CONTENT_TYPES:
                        raise TravelFailure('map_response_rejected', '地图服务响应类型无效')
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise TravelFailure('map_response_rejected', '地图服务响应过大')
                        chunks.append(chunk)
                    body = b''.join(chunks)
                    if self.code.encode() in body:
                        raise TravelFailure('map_response_rejected', '地图服务响应无效')
                    # AMap serves SDK JSONP as JSON or binary. Keep nosniff:
                    # only a validated callback containing JSON is JavaScript.
                    if content_type in {'application/json', 'application/octet-stream'} and (callback := params.get('callback')):
                        try:
                            wrapper = re.fullmatch(r'\s*' + re.escape(callback) + r'\s*\((.*)\)\s*;?\s*',
                                body.decode('utf-8-sig'), re.DOTALL)
                            if not wrapper: raise ValueError('Invalid JSONP wrapper')
                            json.loads(wrapper.group(1))
                        except (UnicodeError, ValueError, RecursionError):
                            raise TravelFailure('map_response_rejected', '地图回调响应无效') from None
                        content_type = 'application/javascript'
                    return Response(body, media_type=content_type,
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        except (httpx.TimeoutException, TimeoutError):
            raise TravelFailure('map_proxy_timeout', '地图服务请求超时', True, 504) from None
        except httpx.HTTPError:
            raise TravelFailure('map_proxy_unavailable', '地图服务连接失败', True) from None


router = APIRouter(dependencies=[Depends(require_user)])


@router.get(PREFIX + '/{path:path}', include_in_schema=False)
async def map_service(path: str, request: Request):
    auth = request.app.state.auth
    auth.check_origin(request)
    referer = None
    if raw := request.headers.get('referer'):
        try:
            parsed = urlsplit(raw)
            origin = f'{parsed.scheme}://{parsed.netloc}'
        except ValueError:
            raise TravelFailure('origin_rejected', '请求来源未获授权', status=403) from None
        if origin not in auth.origins:
            raise TravelFailure('origin_rejected', '请求来源未获授权', status=403)
        referer = origin + '/'
    proxy = request.app.state.map_proxy
    params = proxy.parameters(request, path)
    # Reuse persisted user/global tool quotas and nonblocking concurrency slots.
    with request.app.state.travel.limits.tool(owner_id(request)):
        return await proxy.fetch(path, params, referer)
