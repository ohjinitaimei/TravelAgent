"""Isolated browser acceptance against the explicit TEST ONLY API, never production."""
import os
from contextlib import contextmanager
import json
from datetime import datetime, timezone
from browser_runs import run_id, reserve, case_keys, verify_report
from verification_context import capture,assert_context,tree_digest,digest
from drill_runs import close_service
import argparse
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


@contextmanager
def verification_workspace(destination,metadata):
    """Publish terminal evidence only after the directory context has cleaned up."""
    temporary=tempfile.TemporaryDirectory(prefix='browser-acceptance-',dir=ROOT/'.tmp')
    metadata['cleanup_completed']=False
    try:
        with temporary as folder:
            yield Path(folder)
        metadata['cleanup_completed']=not Path(temporary.name).exists()
        metadata['passed']=bool(metadata.get('passed') and metadata['cleanup_completed'])
    except BaseException as error:
        metadata.update(passed=False,failure_type=type(error).__name__,
                        cleanup_completed=not Path(temporary.name).exists())
        raise
    finally:
        metadata['completed_at']=datetime.now(timezone.utc).isoformat()
        (destination/'run.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')


def verify(suite,browser,grep=None,identifier=None):
    identifier=run_id(identifier)
    destination=reserve(ROOT,identifier,browser,suite)
    metadata={"run_id":identifier,"browser":browser,"suite":suite,"grep":grep,"complete_suite":not bool(grep),"started_at":datetime.now(timezone.utc).isoformat(),"passed":False,"context":capture(ROOT)}
    metadata_path=destination/"run.json"
    metadata_path.write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    (ROOT/".tmp").mkdir(exist_ok=True)
    env=dict(os.environ,PYTHONIOENCODING="utf-8",E2E_AUTH_TESTS="1" if suite=='auth' else '0',E2E_BROWSER=browser,E2E_SUITE=suite)
    for name in ('AMAP_KEY','AMAP_WEB_KEY','AMAP_JS_KEY','AMAP_JS_SECURITY_CODE','DASHSCOPE_API_KEY','OPENAI_API_KEY','TRAVEL_LLM_API_KEY','VITE_AMAP_JS_KEY','VITE_AMAP_SECURITY_CODE'):
        env[name]=''
    env['E2E_OUTPUT_DIR']=str(destination)
    env.update(TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',VITE_API_BASE_URL='/api/v1/travel')
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(ROOT/".cache/playwright"))
    npm=shutil.which("npm.cmd" if os.name=="nt" else "npm")
    node=shutil.which("node")
    if not npm or not node: raise SystemExit("Node.js/npm is required")
    with socket.socket() as first,socket.socket() as second:
        first.bind(("127.0.0.1",0));second.bind(("127.0.0.1",0))
        api_port,web_port=first.getsockname()[1],second.getsockname()[1]
    with verification_workspace(destination,metadata) as folder:
        folder=Path(folder)
        stop=folder/"stop"
        env.update({"E2E_WEB_PORT":str(web_port),"E2E_STOP_FILE":str(stop),"E2E_BASE_URL":f"http://127.0.0.1:{web_port}",
            "E2E_API_URL":f"http://127.0.0.1:{api_port}/api/v1/travel","TRAVEL_BACKEND_URL":f"http://127.0.0.1:{api_port}","E2E_BUILD_DIR":str(folder/"web-dist")})
        with (folder/"api.log").open("w",encoding="utf-8") as api_log,(folder/"web.log").open("w",encoding="utf-8") as web_log:
            processes=[]
            try:
                command=[sys.executable,"tests/browser_fixture_server.py","--test-fixtures-only","--port",str(api_port),"--db",str(folder/"test.sqlite3"),"--stop-file",str(stop)]
                if suite=='auth': command.append('--auth-fixtures')
                processes.append(subprocess.Popen(command,cwd=ROOT,env=env,stdout=api_log,stderr=subprocess.STDOUT))
                processes.append(subprocess.Popen([node,"scripts/browser_test_web.mjs"],cwd=ROOT,env=env,stdout=web_log,stderr=subprocess.STDOUT))
                deadline=time.monotonic()+30
                for url in (env["E2E_API_URL"]+"/auth/status",env["E2E_BASE_URL"]):
                    while time.monotonic()<deadline:
                        if any(process.poll() is not None for process in processes): raise RuntimeError("Acceptance service exited")
                        try:
                            with urllib.request.urlopen(url,timeout=1): break
                        except (urllib.error.URLError,TimeoutError): time.sleep(.1)
                    else: raise RuntimeError("Acceptance service did not become ready")
                if suite=='resilience':metadata['web_build']=tree_digest(folder/'web-dist')
                discover=[node,str(ROOT/'node_modules/@playwright/test/cli.js'),'test','--project',browser,'--list','--reporter=json']
                if grep:discover.extend(['--grep',grep])
                listing=subprocess.run(discover,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',check=True)
                planned,_=case_keys(json.loads(listing.stdout))
                metadata['planned_cases']=planned
                metadata_path.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
                command=[npm,"run","test:browser","--","--project",browser]
                if grep: command.extend(['--grep',grep])
                subprocess.run(command,cwd=ROOT,env=env,check=True)
                report=json.loads((destination/'report.json').read_text(encoding='utf-8'))
                metadata['passed_count']=verify_report(report,planned)
                metadata['report_sha256']=digest((destination/'report.json').read_bytes())
                assert_context(metadata['context'],capture(ROOT))
                if suite=='resilience' and metadata['web_build']!=tree_digest(folder/'web-dist'):raise ValueError('Web build changed during browser verification')
                metadata['passed']=True
            except Exception:
                api_log.flush();web_log.flush()
                shutil.copyfile(folder/"api.log",destination/"api.log");shutil.copyfile(folder/"web.log",destination/"web.log")
                raise
            finally:
                stop.touch()
                graceful=True
                metadata['service_exits']=[]
                for index,process in enumerate(processes):
                    result=close_service(process,'api' if index==0 else 'web',timeout=10)
                    result['service']=result.pop('name')
                    metadata['service_exits'].append(result)
                    graceful=graceful and result['returncode']==0 and not result['forced']
                # Keep logs before cleanup even if graceful shutdown succeeded:
                # a later SQLite/filesystem cleanup failure must remain diagnosable.
                api_log.flush();web_log.flush()
                shutil.copyfile(folder/'api.log',destination/'api.log')
                shutil.copyfile(folder/'web.log',destination/'web.log')
                metadata["services_stopped_gracefully"]=graceful
                metadata["passed"]=bool(metadata["passed"] and graceful)
    if not metadata['passed']:raise RuntimeError('Browser verification or graceful shutdown failed')
    print(f"Browser acceptance passed: {identifier}/{browser}/{suite}, isolated TEST ONLY records.")
    return metadata


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['all','local','auth','resilience'],default='all')
    parser.add_argument('--browser',choices=['all','chromium','firefox','webkit'],default='all')
    parser.add_argument('--run-id',help='Immutable evidence group; same engine/suite cannot reuse an ID')
    parser.add_argument('--grep',help='Run matching test names only; omit for full acceptance')
    args=parser.parse_args()
    try:identifier=run_id(args.run_id)
    except ValueError as error:parser.error(str(error))
    print(f"Browser run ID: {identifier}",flush=True)
    for browser in (['chromium','firefox','webkit'] if args.browser=='all' else [args.browser]):
        for suite in (['local','auth','resilience'] if args.suite=='all' else [args.suite]): verify(suite,browser,args.grep,identifier)


if __name__=="__main__": main()
