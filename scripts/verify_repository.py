"""Reproduce CI locally: isolated DB, no model/Amap credentials or business API calls."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from browser_runs import run_id
from verification_context import capture,assert_context,digest,normalized
from verification_counts import python_passed,client_passed

ROOT=Path(__file__).resolve().parents[1]


def verify():
    (ROOT/".tmp").mkdir(exist_ok=True)
    env=dict(os.environ,TRAVEL_PRODUCTION="1",TRAVEL_AGENT_ENABLED="0",TRAVEL_TOOL_TRANSPORT="direct",TRAVEL_AUTH_MODE="local",TRAVEL_COOKIE_SECURE="0",LLM_INTENT_DISABLE_LLM="1",PYTHONIOENCODING="utf-8")
    env.update(TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',TRAVEL_CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173',VITE_API_BASE_URL='/api/v1/travel')
    for name in ("AMAP_KEY","AMAP_WEB_KEY","AMAP_JS_KEY","AMAP_JS_SECURITY_CODE","DASHSCOPE_API_KEY","OPENAI_API_KEY","TRAVEL_LLM_API_KEY","VITE_AMAP_JS_KEY","VITE_AMAP_SECURITY_CODE"):
        env[name]=""
    npm=shutil.which("npm.cmd" if os.name=="nt" else "npm")
    if not npm:
        raise SystemExit("Node.js/npm is required")
    def run(*command):
        result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8')
        print(result.stdout,end='',flush=True);print(result.stderr,end='',file=sys.stderr,flush=True)
        result.check_returncode();return result.stdout+result.stderr
    python=[]
    for path in sorted((ROOT/'tests').glob('test_*.py')):
        output=run(sys.executable,str(path),'-v')
        python.append({'path':path.relative_to(ROOT).as_posix(),'passed':python_passed(output)})
    with tempfile.TemporaryDirectory(prefix="travelagent-check-",dir=ROOT/".tmp") as directory:
        env["TRAVEL_DB_PATH"]=str(Path(directory)/"verification.sqlite3")
        with socket.socket() as port_probe:
            port_probe.bind(("127.0.0.1",0))
            port=port_probe.getsockname()[1]
        base=f"http://127.0.0.1:{port}/api/v1/travel"
        env["TRAVEL_TEST_URL"]=base
        log_path=Path(directory)/"api.log"
        stop_file=Path(directory)/"stop"
        with log_path.open("w",encoding="utf-8") as log:
            process=subprocess.Popen([sys.executable,"scripts/verification_server.py","--port",str(port),"--stop-file",str(stop_file)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Verification API exited; inspect isolated api.log")
                    try:
                        with urllib.request.urlopen(base+"/capabilities",timeout=1): break
                    except (urllib.error.URLError,TimeoutError): time.sleep(.1)
                else:
                    raise RuntimeError("Verification API did not become ready")
                client_output=run(npm,"run","test:client")
            finally:
                # Let FastAPI lifespan close workers and SQLite before deleting
                # the isolated test folder. Windows terminate() is not graceful.
                stop_file.touch()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=5)
                    raise RuntimeError('Verification API required forced termination') from None
                if process.returncode!=0:raise RuntimeError('Verification API did not stop gracefully')
    client_count=client_passed(client_output)
    schemas=[ROOT/'packages/api-schema'/name for name in ('openapi.json','schema.d.ts')]
    before={p.name:digest(normalized(p.read_bytes())) for p in schemas}
    run(sys.executable,'scripts/export_openapi.py');run(npm,'run','schema:generate')
    if before!={p.name:digest(normalized(p.read_bytes())) for p in schemas}:raise ValueError('Generated schema drift')
    run(sys.executable,'scripts/verify_web_build.py')
    from verify_web_build import validate
    print("Repository checks passed (isolated API, no live credentials).")
    return {'python_suites':python,'python':sum(item['passed'] for item in python),'typescript':client_count,
            'schema_consistent':True,'schema_sha256':before,'services_stopped_gracefully':True,'web_build':validate()['web_build']}


def main():
    # Node's Unicode result markers must survive Windows redirected GBK consoles.
    # Child output is already captured as UTF-8; use the same encoding when relaying it.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id');args=parser.parse_args()
    identifier=run_id(args.run_id)
    destination=ROOT/'artifacts/repository-runs'/identifier;destination.mkdir(parents=True,exist_ok=False)
    metadata={'run_id':identifier,'status':'running','passed':False,'context':capture(ROOT),
              'started_at':datetime.now(timezone.utc).isoformat(),'python_version':sys.version.split()[0]}
    try:
        metadata.update(verify());assert_context(metadata['context'],capture(ROOT))
        metadata.update(status='passed',passed=True)
    except Exception as error:
        metadata.update(status='failed',error_type=type(error).__name__);raise
    finally:
        metadata['completed_at']=datetime.now(timezone.utc).isoformat()
        (destination/'report.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')


if __name__=="__main__":
    main()
