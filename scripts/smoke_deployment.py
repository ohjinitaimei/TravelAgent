"""Read-only HTTPS edge checks. No login, task creation or external provider calls."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import ssl
from urllib.parse import urlsplit

import httpx
from check_deployment import origin


class Assets(HTMLParser):
    def __init__(self):super().__init__();self.paths=[]
    def handle_starttag(self,tag,attrs):
        for name,value in attrs:
            if tag in {'script','link'} and name in {'src','href'} and value and value.startswith('/assets/'):
                self.paths.append(value)


def smoke(site,ca_file=None,http_origin=None):
    site=origin(site)
    context=ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    passed=[]
    def check(ok,name):
        if not ok:raise ValueError(name+' 未通过')
        passed.append(name)
    with httpx.Client(base_url=site,verify=context,timeout=10,follow_redirects=False,trust_env=False) as client:
        for path,status in [('/health/live','alive'),('/health/ready','ready')]:
            r=client.get(path)
            check(r.status_code==200 and r.json()=={'status':status} and r.headers.get('cache-control')=='no-store',path)
        r=client.get('/')
        check(r.status_code==200 and 'text/html' in r.headers.get('content-type',''),'production HTML')
        check(r.headers.get('cache-control')=='no-cache','HTML refresh policy')
        check(r.headers.get('x-content-type-options')=='nosniff' and r.headers.get('x-frame-options')=='DENY'
              and 'max-age=31536000' in r.headers.get('strict-transport-security',''),'edge headers')
        assets=Assets();assets.feed(r.text)
        check(len(assets.paths)>=2 and any(p.endswith('.js') for p in assets.paths),'built assets referenced')
        for path in assets.paths:
            asset=client.get(path)
            check(asset.status_code==200 and 'immutable' in asset.headers.get('cache-control','')
                  and 'text/html' not in asset.headers.get('content-type',''),'asset '+path)
        r=client.get('/api/v1/travel/auth/status')
        check(r.status_code==200 and r.json()['mode']=='session' and not r.json()['authenticated'],'anonymous session status')
        for path in ['/api/v1/travel/itineraries','/api/v1/travel/_AMapService/v4/map/styles']:
            r=client.get(path)
            check(r.status_code==401 and r.json()['error']['code']=='authentication_required'
                  and r.headers.get('cache-control')=='no-store','private '+path)
        r=client.get('/api/route/generate')
        check(r.status_code==410,'legacy disabled')
        for path in ['/.env','/backend/.env','/assets/not-a-real-file.js','/openapi.json']:
            check(client.get(path).status_code==404,'not published '+path)
        if http_origin:
            value=urlsplit(http_origin)
            check(value.scheme=='http' and value.hostname==urlsplit(site).hostname and value.path in ('','/')
                  and not value.username and not value.query and not value.fragment,'redirect origin')
            r=client.get(http_origin.rstrip('/')+'/')
            check(r.status_code in {301,302,307,308} and r.headers.get('location')==site+'/','HTTP to HTTPS')
    return passed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--ca-file',type=Path,help='Explicit private CA for isolated local TLS; verification stays enabled')
    parser.add_argument('--http-origin',help='Optional HTTP source to verify redirect')
    args=parser.parse_args()
    try:checks=smoke(args.origin,args.ca_file,args.http_origin)
    except (OSError,ValueError,KeyError,httpx.HTTPError):
        parser.exit(1,'上线检查失败：核对 HTTPS 信任、入口配置和服务状态；未输出响应正文或凭证。\n')
    print(f'HTTPS 上线只读检查通过：{len(checks)} 项。未登录、创建任务或调用外部数据。')


if __name__=='__main__':main()
