"""Explicit TEST ONLY server for browser editing QA. Never imported by production.

Launch with --test-fixtures-only; binds only localhost:8001 and uses an isolated DB.
All fixture names and sources identify test inputs. No runtime fallback exists.
"""
import os
from pathlib import Path
import sys
import argparse
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"backend"))


def browser_worker(payload, output):
    # Spawned test process imports only explicitly test-owned fixtures.
    from test_travel import fixture_worker
    from test_agent_intake import draft_fixture_worker
    if payload.get("kind") == "draft":
        from test_agent_intake import FixtureLLM
        from agent.travel_intake import create_draft
        from travel.schemas import DraftRequest
        request=DraftRequest.model_validate(payload["request"])
        if request.text=="TEST ONLY 想逛博物馆，需要预约":
            arguments={"values":{"query":"博物馆"},"evidence":{"query":"博物馆"},"unhandled_requirements":["需要预约"]}
            result=create_draft(request,lambda stage,message:output.put({"kind":"event","stage":stage,"message":message}),llm=FixtureLLM(arguments))
            output.put({"kind":"result","data":result.model_dump(mode="json")})
            return
        return draft_fixture_worker(payload,output)
    query=payload["request"]["query"]
    if query=="TEST ONLY maximum":
        from maximum_fixture import maximum_fixture_worker
        return maximum_fixture_worker(payload,output)
    if query=="TEST ONLY geographic":
        from test_day_grouping import geographic_fixture_worker
        return geographic_fixture_worker(payload,output)
    if query=="TEST ONLY shared endpoints":
        from test_journey_endpoints import EndpointProvider
        from travel.planner import plan
        from travel.schemas import PlanRequest
        result=plan(PlanRequest.model_validate(payload['request']),
            lambda stage,message:output.put({'kind':'event','stage':stage,'message':message}),
            provider=EndpointProvider(),poi_ids_by_day=payload.get('poi_ids_by_day'),
            optimize_order=payload.get('optimize_order',True),parent_id=payload.get('parent_id'))
        output.put({'kind':'result','data':result.model_dump(mode='json')})
        return
    if query=="TEST ONLY retry":
        marker=Path(os.environ["TRAVEL_TEST_MARKER"])
        if not marker.exists():
            marker.write_text("TEST ONLY",encoding="utf-8")
            output.put({"kind":"error","data":{"code":"provider_timeout","message":"TEST ONLY 临时连接失败","retryable":True}})
            return
    if query=="TEST ONLY slow": time.sleep(2)
    return fixture_worker(payload,output)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--test-fixtures-only",action="store_true",required=True)
    parser.add_argument("--port",type=int,default=8001)
    parser.add_argument("--db",type=Path,default=ROOT/".tmp/browser-test.sqlite3")
    parser.add_argument("--stop-file",type=Path)
    parser.add_argument("--auth-fixtures",action="store_true")
    parser.add_argument("--secure-cookies",action="store_true",help="TEST ONLY HTTPS gateway acceptance")
    args=parser.parse_args()
    if not args.test_fixtures_only or not args.db.resolve().is_relative_to((ROOT/".tmp").resolve()):
        raise SystemExit("Requires explicit --test-fixtures-only; never a production server")
    from test_travel import FixtureProvider, fixture_worker
    from test_agent_intake import draft_fixture_worker
    from travel.planner import plan
    from travel.schemas import PlanRequest, Task
    from travel.store import Store
    import travel.tasks
    import uvicorn

    directory = args.db.resolve().parent
    directory.mkdir(exist_ok=True)
    os.environ["TRAVEL_DB_PATH"] = str(args.db.resolve())
    os.environ["TRAVEL_AUTH_MODE"]="session" if args.auth_fixtures else "local"
    os.environ["TRAVEL_COOKIE_SECURE"]="1" if args.secure_cookies else "0"
    os.environ["TRAVEL_TOOL_TRANSPORT"]="direct"
    # This explicit TEST ONLY service runs the entire suite under one local owner.
    # Production quota/429 behavior is independently exercised in test_business_limits.py.
    os.environ["TRAVEL_LIMIT_TASKS"]="100"
    os.environ["TRAVEL_TEST_MARKER"]=str(directory/"test-only-failure-marker")
    os.environ["TRAVEL_CORS_ORIGINS"] = os.getenv('E2E_BASE_URL',"http://127.0.0.1:5174")
    store=Store(Path(os.environ["TRAVEL_DB_PATH"]))
    request=PlanRequest(city="TEST ONLY 测试城市",query="TEST ONLY 地点",start_date="2026-10-10",days=2,stops_per_day=2,budget=100)
    trip=plan(request,lambda *_:None,provider=FixtureProvider(),poi_ids_by_day=[["fixture-a","fixture-b"],["fixture-c","fixture-d"]],optimize_order=False)
    store.succeed(Task(id="test-only-"+trip.id,status="running"),trip)
    from pagination_fixture import seed_history
    seed_history(store,trip)
    if args.auth_fixtures:
        from travel.auth import AuthService
        auth=AuthService(store)
        for name in ('alpha','beta','draft-alpha','draft-beta'):
            user=auth.create_user('test-'+name,'TEST ONLY account password 2026')
            request=PlanRequest(city='TEST ONLY '+name,query='TEST ONLY 地点',start_date='2026-10-20',days=1,stops_per_day=2)
            trip=plan(request,lambda *_:None,provider=FixtureProvider())
            task=Task(id='test-user-'+trip.id,status='running')
            store.register_task(task,{'request':request.model_dump(mode='json')},None,'test-only',owner_id=user.id)
            store.succeed(task,trip)
        for name in ('page-alpha','page-beta'):
            user=auth.create_user('test-'+name,'TEST ONLY account password 2026')
            seed_history(store,trip,owner=user.id)
    store.close()
    os.environ["TRAVEL_AGENT_ENABLED"]="1"
    os.environ["LLM_INTENT_DISABLE_LLM"]="0"
    os.environ["TRAVEL_LLM_API_KEY"]="TEST_ONLY_NOT_A_REAL_KEY"
    os.environ["TRAVEL_LLM_BASE_URL"]="https://test.invalid/v1"
    os.environ["TRAVEL_LLM_MODEL"]="test-only"
    travel.tasks.run=browser_worker
    server=uvicorn.Server(uvicorn.Config("main:app",host="127.0.0.1",port=args.port))
    if args.stop_file:
        def stop_when_requested():
            while not args.stop_file.exists(): time.sleep(.1)
            server.should_exit=True
        threading.Thread(target=stop_when_requested,daemon=True).start()
    server.run()
