"""Explicit TEST ONLY server for browser editing QA. Never imported by production.

Launch with --test-fixtures-only; binds only localhost:8001 and uses an isolated DB.
All fixture names and sources identify test inputs. No runtime fallback exists.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"backend"))


def browser_worker(payload, output):
    # Spawned test process imports only explicitly test-owned fixtures.
    from test_travel import fixture_worker
    from test_agent_intake import draft_fixture_worker
    if payload.get("kind") == "draft":
        return draft_fixture_worker(payload,output)
    return fixture_worker(payload,output)


if __name__ == "__main__":
    if sys.argv[1:] != ["--test-fixtures-only"]:
        raise SystemExit("Requires explicit --test-fixtures-only; never a production server")
    from test_travel import FixtureProvider, fixture_worker
    from test_agent_intake import draft_fixture_worker
    from travel.planner import plan
    from travel.schemas import PlanRequest, Task
    from travel.store import Store
    import travel.tasks
    import uvicorn

    directory = ROOT/".tmp"
    directory.mkdir(exist_ok=True)
    os.environ["TRAVEL_DB_PATH"] = str(directory/"browser-test.sqlite3")
    os.environ["TRAVEL_CORS_ORIGINS"] = "http://127.0.0.1:5174"
    store=Store(Path(os.environ["TRAVEL_DB_PATH"]))
    request=PlanRequest(city="TEST ONLY 测试城市",query="TEST ONLY 地点",start_date="2026-10-10",days=2,stops_per_day=2,budget=100)
    trip=plan(request,lambda *_:None,provider=FixtureProvider(),poi_ids_by_day=[["fixture-a","fixture-b"],["fixture-c","fixture-d"]],optimize_order=False)
    store.succeed(Task(id="test-only-"+trip.id,status="running"),trip)
    store.close()
    os.environ["TRAVEL_AGENT_ENABLED"]="1"
    os.environ["LLM_INTENT_DISABLE_LLM"]="0"
    os.environ["TRAVEL_LLM_API_KEY"]="TEST_ONLY_NOT_A_REAL_KEY"
    os.environ["TRAVEL_LLM_BASE_URL"]="https://test.invalid/v1"
    os.environ["TRAVEL_LLM_MODEL"]="test-only"
    travel.tasks.run=browser_worker
    uvicorn.run("main:app",app_dir=str(ROOT/"backend"),host="127.0.0.1",port=8001)
