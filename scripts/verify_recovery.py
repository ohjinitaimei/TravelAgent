"""Trusted release -> HTTPS -> online snapshots -> offline restore/rollback, TEST ONLY."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
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
import zipfile

import httpx
from package_release import LIMIT, ROOT, verify_archive
from smoke_deployment import smoke
from drill_runs import begin, close_service, finish, reserve, save
from verification_context import capture, fingerprint, normalized, selected


def saved_records(client,identifiers):
    """Read complete A/B DTOs and completed receipts, not lossy listing summaries."""
    def read(path):
        response=client.get('/api/v1/travel/'+path)
        if response.status_code!=200:raise AssertionError('TEST ONLY saved record could not be read')
        return response.json()
    return {'itineraries':{identifier:read('itineraries/'+identifier) for identifier in identifiers['itinerary_ids']},
        'draft':read('drafts/'+identifiers['draft_id']),
        'receipts':{key:read('submissions/'+key) for key in identifiers['receipt_keys']}}


def same_records(actual,expected):
    if actual!=expected:raise AssertionError('Complete A/B saved DTO or receipt changed during recovery')


def run(archive,caddy,identifier=None):
    if archive.stat().st_size>LIMIT:raise ValueError('Archive too large')
    data=archive.read_bytes();metadata=verify_archive(io.BytesIO(data))
    caddy=caddy.resolve();version=subprocess.check_output([str(caddy),'version'],text=True).split()[0]
    if version!='v2.11.7':raise ValueError('Validated Caddy v2.11.7 required')
    destination=reserve(ROOT,identifier,'recovery');context=capture(ROOT)
    release_sha256=hashlib.sha256(data).hexdigest()
    lifecycle=begin(destination,source='TEST ONLY archived service; no real provider calls',context=context,
        release_commit=metadata['git_commit'],release_sha256=release_sha256)
    report={'status':'running','source':'TEST ONLY archived service; no real provider calls',
            'run_id':lifecycle['run_id'],'context':context,'release_commit':metadata['git_commit'],
            'archive_sha256':release_sha256,'release_sha256':release_sha256,
            'working_tree_dirty':metadata['working_tree_dirty'],'caddy':version,'checks':[]}
    def persist():
        report['timestamp']=datetime.now(timezone.utc).isoformat()
        save(destination,report)
    def check(condition,label):
        if not condition:raise AssertionError(label)
        report['checks'].append(label)
    persist();(ROOT/'.tmp').mkdir(exist_ok=True)
    sockets=[socket.socket() for _ in range(4)]
    try:
        for sock in sockets:sock.bind(('127.0.0.1',0))
        api_port,tls_port,http_port,admin_port=[sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:sock.close()
    services=[];failure=None;cleanup_completed=False;cleanup_errors=[]
    try:
      with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        archive_files=[]
        for entry in metadata['files']:
            name=entry['path']
            if not name.startswith('source/') or not selected(name[7:]):continue
            content=normalized(zipped.read(name))
            archive_files.append({'path':name[7:],'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
        report['archive_source_fingerprint']=fingerprint(archive_files)
      check(report['archive_source_fingerprint']==context['fingerprint'],'release archived source matches verification context')
      with tempfile.TemporaryDirectory(prefix='recovery-drill-',dir=ROOT/'.tmp') as name:
        folder=Path(name)
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:zipped.extractall(folder)
        source=folder/'source';live=folder/'live.sqlite3';restored=folder/'restored.sqlite3';rollback=folder/'rollback.sqlite3'
        site=f'https://127.0.0.1:{tls_port}';http_site=f'http://127.0.0.1:{http_port}'
        env=dict(os.environ,TRAVEL_PRODUCTION='1',TRAVEL_AUTH_MODE='session',TRAVEL_COOKIE_SECURE='1',
            TRAVEL_CORS_ORIGINS=site,TRAVEL_TOOL_TRANSPORT='direct',TRAVEL_AGENT_ENABLED='0',LLM_INTENT_DISABLE_LLM='1',
            TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',
            TRAVEL_SITE=site,TRAVEL_HTTP_SITE=http_site,TRAVEL_BIND='127.0.0.1',TRAVEL_TLS='tls internal',
            TRAVEL_WEB_ROOT=(folder/'web').as_posix(),TRAVEL_UPSTREAM=f'127.0.0.1:{api_port}',
            TRAVEL_CADDY_ADMIN=f'127.0.0.1:{admin_port}',TRAVEL_CADDY_DATA=(folder/'certificates').as_posix(),
            XDG_DATA_HOME=str(folder/'caddy-data'),XDG_CONFIG_HOME=str(folder/'caddy-config'))
        env.pop('PYTHONPATH',None)
        for key in ('AMAP_KEY','AMAP_WEB_KEY','AMAP_JS_KEY','AMAP_JS_SECURITY_CODE','DASHSCOPE_API_KEY','OPENAI_API_KEY',
                    'TRAVEL_LLM_API_KEY','VITE_AMAP_JS_KEY','VITE_AMAP_SECURITY_CODE'):env[key]=''
        processes=[];api=None;gateway=None;stop=None
        with (folder/'api.log').open('w',encoding='utf-8') as api_log,(folder/'gateway.log').open('w',encoding='utf-8') as gateway_log:
            def command(*args,cwd=source,parse_json=True):
                result=subprocess.run([sys.executable,*args],cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
                if result.returncode:raise ValueError('Isolated child command failed')
                return json.loads(result.stdout.splitlines()[-1]) if parse_json and result.stdout.strip() else None
            def seed(phase):
                return command(str(ROOT/'tests/recovery_seed.py'),'--test-fixtures-only','--source',str(source),'--db',str(live),'--phase',phase)
            def stop_api():
                nonlocal api
                if api is not None and api.poll() is None:
                    stop.touch();api.wait(timeout=15)
                    check(api.returncode==0,'API stopped gracefully')
                api=None
            def start_api(database):
                nonlocal api,stop
                stop=folder/('stop-'+database.stem);env['TRAVEL_DB_PATH']=str(database)
                api=subprocess.Popen([sys.executable,str(source/'scripts/verification_server.py'),'--port',str(api_port),
                    '--stop-file',str(stop)],cwd=source,env=env,stdout=api_log,stderr=subprocess.STDOUT)
                processes.append((database.stem+' API',api))
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if api.poll() is not None:raise ValueError('Archived API exited')
                    try:
                        with httpx.Client(trust_env=False,timeout=1) as probe:
                            if probe.get(f'http://127.0.0.1:{api_port}/health/ready').status_code==200:return
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                raise TimeoutError('Archived API not ready')
            def snapshot():
                value=command('-m','travel.backup_schedule','--db',str(live),'--root',str(folder/'backups'),'--keep','2',cwd=source/'backend')
                check(value['verified'] and value['removed']==0,'online snapshot verified without pruning')
                return folder/'backups'/value['created']
            def restore(snapshot,target):
                command('-m','travel.backup','restore',str(snapshot),'--db',str(target),'--service-stopped',cwd=source/'backend',parse_json=False)
            def checksum(path):return hashlib.sha256(path.read_bytes()).hexdigest()
            try:
                initial=seed('initial');start_api(live)
                gateway=subprocess.Popen([str(caddy),'run','--config',str(source/'deploy/Caddyfile'),'--adapter','caddyfile'],
                    cwd=source,env=env,stdout=gateway_log,stderr=subprocess.STDOUT)
                processes.append(('HTTPS gateway',gateway));ca=folder/'certificates/pki/authorities/local/root.crt'
                deadline=time.monotonic()+20
                while not ca.is_file() and time.monotonic()<deadline:
                    if gateway.poll() is not None:raise ValueError('Gateway exited')
                    time.sleep(.1)
                context=ssl.create_default_context(cafile=str(ca))
                # CA creation precedes listener/leaf-certificate readiness.
                while time.monotonic()<deadline:
                    if gateway.poll() is not None:raise ValueError('Gateway exited')
                    try:
                        with httpx.Client(verify=context,trust_env=False,timeout=1) as probe:
                            if probe.get(site+'/health/ready').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise TimeoutError('HTTPS edge not ready')
                with httpx.Client(base_url=site,verify=context,trust_env=False,timeout=10) as alpha,\
                     httpx.Client(base_url=site,verify=context,trust_env=False,timeout=10) as beta:
                    clients=[alpha,beta]
                    def login(client,name):
                        r=client.post('/api/v1/travel/auth/login',json={'username':'test-'+name,'password':'TEST ONLY recovery password 2026','transport':'cookie'},
                            headers={'Origin':site,'X-Travel-Client':'web'})
                        check(r.status_code==200,'HTTPS login '+name)
                        return client.get('/api/v1/travel/auth/status').json()['csrf_token']
                    def trips():
                        return [client.get('/api/v1/travel/itineraries').json()['items'] for client in clients]
                    for client,name in zip(clients,('alpha','beta')):login(client,name)
                    before=trips();check(all(len(items)==2 for items in before),'two owners each read an original and adjustment')
                    owners=[initial['owners'][name] for name in ('alpha','beta')]
                    def records():return [saved_records(client,owner) for client,owner in zip(clients,owners)]
                    def isolation(stage):
                        for client,foreign in zip(clients,reversed(owners)):
                            for identifier in foreign['itinerary_ids']:
                                check(client.get('/api/v1/travel/itineraries/'+identifier).status_code==404,'cross-owner trip read denied '+stage)
                            check(client.get('/api/v1/travel/drafts/'+foreign['draft_id']).status_code==404,'cross-owner draft read denied '+stage)
                            for key in foreign['receipt_keys']:
                                check(client.get('/api/v1/travel/submissions/'+key).status_code==404,'cross-owner receipt read denied '+stage)
                    original_records=records()
                    for item,owner in zip(original_records,owners):
                        parent=item['itineraries'][owner['parent_id']];child=item['itineraries'][owner['child_id']];draft=item['draft']
                        comparison=parent['planning_comparison']
                        check(comparison['applied'] and comparison['baseline_days'] and comparison['baseline']['travel_minutes']>comparison['result']['travel_minutes'],
                            'TEST ONLY algorithm produced factual baseline and adopted comparison')
                        check(child['parent_id']==parent['id'] and child['planning_comparison'] is None,'manual adjustment links immutable original')
                        check(draft['revision']==3 and len(draft['clarifications'])==2 and draft['proposal']['values']['day_schedules'][0]['day_end'] is None,
                            'TEST ONLY revisioned draft retains partial daily conditions')
                        check(set(draft['field_sources'].values())=={'model_extracted','user_input'} and bool(draft['proposal']['evidence']) and
                            draft['proposal']['values']['max_leg_travel_minutes']==40 and draft['proposal']['values']['max_daily_travel_minutes']==90 and
                            bool(draft['proposal']['values']['origin_hint']) and bool(draft['proposal']['values']['destination_hint']),
                            'draft evidence, sources, transport limits and unresolved endpoint hints present')
                    isolation('before backup')
                    old_cookie=alpha.cookies.get('travelagent_session')
                    bearer=alpha.post('/api/v1/travel/auth/login',json={'username':'test-alpha','password':'TEST ONLY recovery password 2026','transport':'bearer'},headers={'Origin':site}).json()['access_token']
                    seed('pending');first=snapshot()
                    seed('mutate');check(trips()[1][0]['title']=='TEST ONLY post-snapshot change','source changed after first snapshot')
                    latest_records=records()
                    same_records(latest_records[0],original_records[0])
                    check(latest_records[1]['itineraries'][owners[1]['parent_id']]==original_records[1]['itineraries'][owners[1]['parent_id']],
                        'source parent full DTO unchanged by TEST ONLY child mutation')
                    report['record_sha256']={label:hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                        for label,value in (('first_snapshot',original_records),('latest_snapshot',latest_records))}
                    latest=snapshot();stop_api()
                    check(alpha.get('/health/ready').status_code==502,'gateway reports API unavailable during stop')
                    original_hash=checksum(live);snapshot_hashes={str(p):checksum(p/'snapshot.sqlite3') for p in (first,latest)}
                    restore(first,restored);check(checksum(live)==original_hash,'restore never overwrites source database')
                    start_api(restored)
                    for client in clients:check(client.get('/api/v1/travel/itineraries').status_code==401,'original cookie revoked in restored DB')
                    check(alpha.get('/api/v1/travel/itineraries',headers={'Authorization':'Bearer '+bearer}).status_code==401,'original bearer revoked in restored DB')
                    csrf=login(alpha,'alpha');login(beta,'beta')
                    same_records(records(),original_records)
                    check(True,'first snapshot restores complete itineraries, original comparison facts, drafts and completed receipts')
                    isolation('after restore')
                    pending=beta.get('/api/v1/travel/submissions/test-only-pending').json()
                    check(pending['status']=='failed' and pending['error']['code']=='backup_restored' and pending['retry_available'],'unfinished task requires explicit retry')
                    events=beta.get('/api/v1/travel/tasks/test-only-interrupted/events').json()['items']
                    check(any(e['stage']=='failed' for e in events),'real recovery event persisted')
                    with beta.stream('GET','/api/v1/travel/tasks/test-only-interrupted/events/stream') as stream:
                        check(stream.status_code==200 and 'event: terminal' in stream.read().decode(),'restored task SSE terminal delivered')
                    r=alpha.post('/api/v1/travel/tasks',json={'city':'TEST ONLY','query':'TEST ONLY no key','start_date':'2026-10-20','days':1,'stops_per_day':2},
                        headers={'Origin':site,'X-CSRF-Token':csrf,'Idempotency-Key':'TEST-ONLY-RECOVERED-PLAN'})
                    check(r.status_code==202,'restored API accepts new async task')
                    identifier=r.json()['id'];deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        task=alpha.get('/api/v1/travel/tasks/'+identifier).json()
                        if task['status'] not in {'queued','running'}:break
                        time.sleep(.1)
                    check(task['status']=='failed' and task['error']['code']=='provider_not_configured' and task['itinerary_id'] is None,'archived production provider fails closed without key')
                    check(len(trips()[0])==2,'no synthetic itinerary saved by production API')
                    restored_cookie=alpha.cookies.get('travelagent_session');stop_api()
                    restore(latest,rollback);start_api(rollback)
                    for cookie in (old_cookie,restored_cookie):
                        check(alpha.get('/api/v1/travel/itineraries',headers={'Cookie':'travelagent_session='+cookie}).status_code==401,'rollback clone does not revive old cookies')
                    check(alpha.get('/api/v1/travel/itineraries',headers={'Authorization':'Bearer '+bearer}).status_code==401,'rollback clone revokes snapshot bearer')
                    login(alpha,'alpha');login(beta,'beta')
                    returned=trips();same_records(records(),latest_records)
                    check(True,'rollback restores complete newer saved DTOs, original source facts and completed receipts')
                    check(returned[1][0]['title']=='TEST ONLY post-snapshot change','newer rollback snapshot restored')
                    check(alpha.get('/api/v1/travel/tasks/'+identifier).status_code==404,'post-restore task absent in earlier rollback snapshot')
                    isolation('after rollback')
                    check(checksum(live)==original_hash,'source DB unchanged across both recoveries')
                    check(all(checksum(Path(path)/'snapshot.sqlite3')==value for path,value in snapshot_hashes.items()),'both backup files unchanged')
                report['checks'].extend('final edge: '+label for label in smoke(site,ca,http_site))
                stop_api();report.update(tlsVerification=True,systemTrustModified=False,externalCalls=0)
            except Exception as error:
                report.update(status='failed',exceptionType=type(error).__name__)
                raise
            finally:
                if api is not None and api.poll() is None:
                    try:stop.touch()
                    except OSError as error:cleanup_errors.append(type(error).__name__)
                if gateway is not None and gateway.poll() is None:
                    try:subprocess.run([str(caddy),'stop','--address',env['TRAVEL_CADDY_ADMIN']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                    except (OSError,subprocess.SubprocessError) as error:cleanup_errors.append(type(error).__name__)
                for name,process in processes:services.append(close_service(process,name))
                report['processesStopped']=all(p.poll() is not None for _,p in processes)
                report['gracefulStop']=all(p.returncode==0 for _,p in processes) and all(not service['forced'] for service in services)
                api_log.flush();gateway_log.flush()
                shutil.copyfile(folder/'api.log',destination/'api.log');shutil.copyfile(folder/'gateway.log',destination/'gateway.log')
      cleanup_completed=not cleanup_errors
    except BaseException as error:
        failure=error
    try:completed_context=capture(ROOT)
    except Exception as error:
        if failure is None:failure=error
        completed_context={}
    final=finish(destination,lifecycle,error=failure,services=services,cleanup_completed=cleanup_completed,context=completed_context)
    report.update(status=final['status'],passed=len(report['checks']) if final['status']=='passed' else 0,
        cleanup_completed=cleanup_completed,services=services,services_stopped_gracefully=final['services_stopped_gracefully'],
        context_unchanged=final['context_unchanged'],cleanup_errors=cleanup_errors)
    if failure is not None:report['exceptionType']=type(failure).__name__
    persist()
    if failure is not None:raise failure
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('--caddy',type=Path,required=True)
    parser.add_argument('--run-id',help='Unique drill group; a previous recovery scope is never overwritten')
    args=parser.parse_args()
    try:
        report=run(args.archive,args.caddy,args.run_id)
        if report['status']!='passed':raise ValueError('Process cleanup failed')
    except (OSError,ValueError,KeyError,AssertionError,TimeoutError,subprocess.SubprocessError,httpx.HTTPError,zipfile.BadZipFile):
        parser.exit(1,'本地恢复演练失败；查看 artifacts/drill-runs/<run-id>/recovery/ 的阶段记录。没有操作个人库或系统信任。\n')
    print(f"本地 HTTPS 发布包恢复/回退演练通过：{report['passed']} 项，仅使用 TEST ONLY 记录。")


if __name__=='__main__':main()
