"""Reproduce CI locally: isolated DB, no model/Amap credentials or business API calls."""
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

ROOT=Path(__file__).resolve().parents[1]


def main():
    (ROOT/".tmp").mkdir(exist_ok=True)
    env=dict(os.environ,TRAVEL_PRODUCTION="1",TRAVEL_AGENT_ENABLED="0",TRAVEL_TOOL_TRANSPORT="direct",TRAVEL_AUTH_MODE="local",TRAVEL_COOKIE_SECURE="0",LLM_INTENT_DISABLE_LLM="1",PYTHONIOENCODING="utf-8")
    env.update(TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',TRAVEL_CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173',VITE_API_BASE_URL='/api/v1/travel')
    for name in ("AMAP_KEY","AMAP_WEB_KEY","AMAP_JS_KEY","AMAP_JS_SECURITY_CODE","DASHSCOPE_API_KEY","OPENAI_API_KEY","TRAVEL_LLM_API_KEY","VITE_AMAP_JS_KEY","VITE_AMAP_SECURITY_CODE"):
        env[name]=""
    npm=shutil.which("npm.cmd" if os.name=="nt" else "npm")
    if not npm:
        raise SystemExit("Node.js/npm is required")
    def run(*command):
        subprocess.run(command,cwd=ROOT,env=env,check=True)
    for script in ("test_travel.py","test_agent_intake.py","test_draft_clarification.py","test_mcp.py","test_task_recovery.py","test_mcp_client.py","test_auth.py","test_business_limits.py","test_backup.py","test_day_grouping.py","test_map_proxy.py","test_health.py","test_deployment_config.py","test_backup_schedule.py","test_release_package.py","test_recovery_safety.py","test_live_quality.py","test_time_constraints.py","test_itinerary_listing.py","test_journey_endpoints.py","test_travel_limits.py","test_provider_gate.py","test_daily_endpoints.py"):
        run(sys.executable,str(ROOT/"tests"/script),"-v")
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
                run(npm,"run","test:client")
            finally:
                # Let FastAPI lifespan close workers and SQLite before deleting
                # the isolated test folder. Windows terminate() is not graceful.
                stop_file.touch()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=5)
    run(npm,"run","build")
    print("Repository checks passed (isolated API, no live credentials).")


if __name__=="__main__":
    main()
