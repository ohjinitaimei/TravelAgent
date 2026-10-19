"""Isolated browser acceptance against the explicit TEST ONLY API, never production."""
import os
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


def verify(suite):
    (ROOT/".tmp").mkdir(exist_ok=True)
    env=dict(os.environ,PYTHONIOENCODING="utf-8",E2E_AUTH_TESTS="1" if suite=='auth' else '0')
    for name in ('AMAP_KEY','AMAP_WEB_KEY','DASHSCOPE_API_KEY','OPENAI_API_KEY','TRAVEL_LLM_API_KEY','VITE_AMAP_JS_KEY','VITE_AMAP_SECURITY_CODE'):
        env[name]=''
    env.update(TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',VITE_API_BASE_URL='/api/v1/travel')
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(ROOT/".cache/playwright"))
    npm=shutil.which("npm.cmd" if os.name=="nt" else "npm")
    node=shutil.which("node")
    if not npm or not node: raise SystemExit("Node.js/npm is required")
    with socket.socket() as first,socket.socket() as second:
        first.bind(("127.0.0.1",0));second.bind(("127.0.0.1",0))
        api_port,web_port=first.getsockname()[1],second.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="browser-acceptance-",dir=ROOT/".tmp") as folder:
        folder=Path(folder)
        stop=folder/"stop"
        env.update({"E2E_WEB_PORT":str(web_port),"E2E_STOP_FILE":str(stop),"E2E_BASE_URL":f"http://127.0.0.1:{web_port}",
            "E2E_API_URL":f"http://127.0.0.1:{api_port}/api/v1/travel","TRAVEL_BACKEND_URL":f"http://127.0.0.1:{api_port}"})
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
                subprocess.run([npm,"run","test:browser"],cwd=ROOT,env=env,check=True)
            except Exception:
                destination=ROOT/"artifacts/browser-diagnostics"/suite
                destination.mkdir(parents=True,exist_ok=True)
                api_log.flush();web_log.flush()
                shutil.copyfile(folder/"api.log",destination/"api.log");shutil.copyfile(folder/"web.log",destination/"web.log")
                raise
            finally:
                stop.touch()
                for process in processes:
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.terminate();process.wait(timeout=5)
    print("Browser acceptance passed using isolated TEST ONLY records.")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['all','local','auth'],default='all')
    args=parser.parse_args()
    for suite in (['local','auth'] if args.suite=='all' else [args.suite]): verify(suite)


if __name__=="__main__": main()
