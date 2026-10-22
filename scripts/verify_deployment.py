"""Isolated TEST ONLY HTTPS acceptance using a caller-provided official Caddy binary."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

import httpx
from drill_runs import begin,close_service,finish,reserve,save
from smoke_deployment import smoke
from verification_context import capture,tree_digest

ROOT=Path(__file__).resolve().parents[1]


def verify(caddy,identifier=None):
    destination=reserve(ROOT,identifier,'deployment')
    metadata=begin(destination,source='TEST ONLY isolated HTTPS; no real provider calls',context=capture(ROOT),externalCalls=0)
    checks=[];services=[];failure=None;cleanup_completed=False;version=None;tls_verified=False;web_build=None
    save(destination,{**metadata,'checks':checks})
    print(f"Deployment run: {metadata['run_id']}/deployment",flush=True)
    try:
        caddy=caddy.resolve()
        if not caddy.is_file():raise ValueError('Caddy executable not found')
        version=subprocess.check_output([str(caddy),'version'],text=True,timeout=10).split()[0]
        if version!='v2.11.7':raise ValueError('Use validated Caddy v2.11.7 for this isolated acceptance')
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise ValueError('Node.js/npm required')
        (ROOT/'.tmp').mkdir(exist_ok=True)
        ports=[]
        sockets=[socket.socket() for _ in range(4)]
        try:
            for sock in sockets:sock.bind(('127.0.0.1',0));ports.append(sock.getsockname()[1])
        finally:
            for sock in sockets:sock.close()
        api_port,tls_port,http_port,admin_port=ports
        site=f'https://127.0.0.1:{tls_port}';http_site=f'http://127.0.0.1:{http_port}'
        env=dict(os.environ,TRAVEL_PRODUCTION='1',TRAVEL_CORS_ORIGINS=site,TRAVEL_TASK_TIMEOUT='180')
        for key in ['AMAP_KEY','AMAP_WEB_KEY','AMAP_JS_KEY','AMAP_JS_SECURITY_CODE','DASHSCOPE_API_KEY',
                    'OPENAI_API_KEY','TRAVEL_LLM_API_KEY','VITE_AMAP_JS_KEY','VITE_AMAP_SECURITY_CODE']:
            env[key]=''
        env.update(VITE_API_BASE_URL='/api/v1/travel',TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800')
        with tempfile.TemporaryDirectory(prefix='deployment-acceptance-',dir=ROOT/'.tmp') as name:
            folder=Path(name);stop=folder/'stop';web=folder/'web';data=folder/'certificates'
            env.update(TRAVEL_SITE=site,TRAVEL_HTTP_SITE=http_site,TRAVEL_BIND='127.0.0.1',E2E_BASE_URL=site,
                XDG_DATA_HOME=str(folder/'caddy-runtime'),XDG_CONFIG_HOME=str(folder/'caddy-config'),
                TRAVEL_WEB_ROOT=web.as_posix(),TRAVEL_UPSTREAM=f'127.0.0.1:{api_port}',
                TRAVEL_CADDY_ADMIN=f'127.0.0.1:{admin_port}',TRAVEL_TLS='tls internal',TRAVEL_CADDY_DATA=data.as_posix())
            processes=[]
            with (folder/'api.log').open('w',encoding='utf-8') as api_log,(folder/'gateway.log').open('w',encoding='utf-8') as gateway_log:
                try:
                    subprocess.run([npm,'exec','--','vite','build','apps/web','--config',str(ROOT/'apps/web/vite.config.ts'),
                        '--outDir',str(web)],cwd=ROOT,env=env,check=True,timeout=120)
                    web_build=tree_digest(web)
                    subprocess.run([str(caddy),'validate','--config','deploy/Caddyfile','--adapter','caddyfile'],
                        cwd=ROOT,env=env,check=True,stdout=gateway_log,stderr=subprocess.STDOUT,timeout=30)
                    processes.append(subprocess.Popen([sys.executable,'tests/browser_fixture_server.py','--test-fixtures-only',
                        '--auth-fixtures','--secure-cookies','--port',str(api_port),'--db',str(folder/'test.sqlite3'),
                        '--stop-file',str(stop)],cwd=ROOT,env=env,stdout=api_log,stderr=subprocess.STDOUT))
                    processes.append(subprocess.Popen([str(caddy),'run','--config','deploy/Caddyfile','--adapter','caddyfile'],
                        cwd=ROOT,env=env,stdout=gateway_log,stderr=subprocess.STDOUT))
                    ca=data/'pki/authorities/local/root.crt'
                    deadline=time.monotonic()+30
                    while time.monotonic()<deadline:
                        if any(p.poll() is not None for p in processes):raise RuntimeError('Acceptance process exited')
                        if ca.is_file():
                            try:
                                with httpx.Client(verify=ssl.create_default_context(cafile=str(ca)),trust_env=False,timeout=1) as client:
                                    if client.get(site+'/health/ready').status_code==200:break
                            except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise TimeoutError('HTTPS acceptance not ready')
                    checks=smoke(site,ca,http_site)
                    tls_verified=True
                    def check(condition,label):
                        if not condition:raise AssertionError(label)
                        checks.append(label)
                    with httpx.Client(base_url=site,verify=ssl.create_default_context(cafile=str(ca)),trust_env=False,timeout=15) as client:
                        r=client.post('/api/v1/travel/auth/login',json={'username':'test-alpha','password':'TEST ONLY account password 2026','transport':'cookie'},
                            headers={'Origin':site,'X-Travel-Client':'web'})
                        check(r.status_code==200,'secure login through forwarded HTTPS')
                        cookie=r.headers.get('set-cookie','')
                        check('Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie,'secure cookie flags')
                        status=client.get('/api/v1/travel/auth/status').json()
                        headers={'Origin':site,'X-CSRF-Token':status['csrf_token'],'Idempotency-Key':'TEST-ONLY-HTTPS-SUBMISSION'}
                        request={'city':'TEST ONLY HTTPS','query':'TEST ONLY slow','start_date':'2026-10-20','days':1,'stops_per_day':2}
                        denied=client.post('/api/v1/travel/tasks',json=request,headers={'Origin':site})
                        check(denied.status_code==403 and denied.json()['error']['code']=='csrf_invalid','CSRF preserved through edge')
                        r=client.post('/api/v1/travel/tasks',json=request,headers=headers)
                        check(r.status_code==202,'async task accepted through edge');task=r.json()
                        repeated=client.post('/api/v1/travel/tasks',json=request,headers=headers)
                        check(repeated.status_code==202 and repeated.json()['id']==task['id'],'idempotency preserved')
                        started=time.monotonic();progress=None;terminal=None
                        with client.stream('GET',f"/api/v1/travel/tasks/{task['id']}/events/stream") as stream:
                            check(stream.status_code==200 and 'text/event-stream' in stream.headers.get('content-type',''),'SSE content type')
                            event=''
                            for line in stream.iter_lines():
                                if line.startswith('event: '):event=line[7:]
                                if line.startswith('data: '):
                                    value=json.loads(line[6:])
                                    if event=='progress' and progress is None:progress=time.monotonic()-started
                                    if event=='terminal':terminal=value;break
                        check(progress is not None and progress<2,'SSE progress arrives before slow task completes')
                        check(terminal and terminal['status']=='succeeded','SSE terminal delivered')
                        r=client.get('/api/v1/travel/itineraries/'+terminal['itinerary_id'])
                        check(r.status_code==200 and len(r.json()['days'][0]['stops'])==2,'saved result through edge')
                        r=client.post('/api/v1/travel/auth/logout',headers=headers)
                        check(r.status_code==200 and client.get('/api/v1/travel/itineraries').status_code==401,'logout revokes proxied session')
                        # A large invalid body must be stopped before reaching a business operation.
                        r=client.post('/api/v1/travel/auth/login',content='x'*70000,headers={'Content-Type':'application/json'})
                        check(r.status_code==413 and r.json()['error']['code']=='gateway_rejected','gateway request size limit')
                except BaseException as error:
                    failure=error
                finally:
                    try:
                        stop.touch()
                        if len(processes)>1 and processes[1].poll() is None:
                            subprocess.run([str(caddy),'stop','--address',env['TRAVEL_CADDY_ADMIN']],cwd=ROOT,env=env,
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=True)
                    except BaseException as error:
                        if failure is None:failure=error
                    # Every started process is checked, including after a failed assertion.
                    for index,process in enumerate(processes):
                        services.append(close_service(process,('api','gateway')[index]))
                    try:
                        api_log.flush();gateway_log.flush()
                        shutil.copyfile(folder/'api.log',destination/'api.log')
                        shutil.copyfile(folder/'gateway.log',destination/'gateway.log')
                    except BaseException as error:
                        if failure is None:failure=error
        cleanup_completed=True
    except BaseException as error:
        if failure is None:failure=error
    try:
        current_context=capture(ROOT)
    except BaseException as error:
        current_context={}
        if failure is None:failure=error
    metadata=finish(destination,metadata,error=failure,services=services,
        cleanup_completed=cleanup_completed,context=current_context,web_build=web_build)
    report={**metadata,'caddy':version,'timestamp':metadata['completed_at'],
        'checks':checks,'completedChecks':checks,'completed_check_count':len(checks),
        'passed':len(checks) if metadata['passed'] else 0,
        'tlsVerification':tls_verified,'systemTrustModified':False,'externalCalls':0}
    save(destination,report)
    if failure is not None:raise failure
    if not metadata['passed']:raise RuntimeError('HTTPS verification or graceful shutdown failed')
    print(f'Isolated HTTPS deployment acceptance passed: {len(checks)} checks; no system service or trust installation.')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caddy',type=Path,required=True,help='Installed Caddy 2.11.7 binary; no system service is installed')
    parser.add_argument('--run-id',help='Immutable drill evidence group; this scope cannot reuse an ID')
    args=parser.parse_args()
    verify(args.caddy,args.run_id)


if __name__=='__main__':main()
