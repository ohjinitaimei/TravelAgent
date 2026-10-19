"""Test fixtures ONLY. No test provider is configurable in the production app."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from services.amap_client import AmapClient
from travel.planner import plan
from travel.provider import AmapProvider, TravelFailure
from travel.schemas import PlanRequest, Poi, Point, Segment, Source, Task
from travel.store import Store
from travel.tasks import TaskManager

PAYLOAD = {"city": "测试城市", "query": "测试地点", "start_date": "2026-10-10", "days": 1, "stops_per_day": 2}


class FixtureProvider:
    """Synthetic inputs for isolated tests; never production fallback."""
    def search(self, *_):
        return [self.detail("fixture-a"), self.detail("fixture-b")]

    def detail(self, poi_id):
        return Poi(id=poi_id, name="TEST ONLY " + poi_id, longitude=116.1 if poi_id == "fixture-a" else 116.2,
                   latitude=39.9, source=Source(provider="user_input"), missing_fields=["rating", "average_spend", "opening_hours"])

    def route(self, origin, destination, mode):
        return Segment(origin_id=origin.id, destination_id=destination.id, mode=mode, distance_km=12.0,
                       duration_min=37, source=Source(provider="user_input"),
                       polyline=[Point(longitude=origin.longitude, latitude=origin.latitude), Point(longitude=destination.longitude, latitude=destination.latitude)])


def fixture_worker(payload, output):
    result = plan(PlanRequest.model_validate(payload["request"]),
                  lambda stage, message: output.put({"kind": "event", "stage": stage, "message": message}),
                  provider=FixtureProvider(), poi_ids_by_day=payload.get("poi_ids_by_day"),
                  optimize_order=payload.get("optimize_order", True), parent_id=payload.get("parent_id"))
    output.put({"kind": "result", "data": result.model_dump(mode="json")})


def stalled_worker(payload, output):
    time.sleep(30)


class ProviderTests(unittest.TestCase):
    def test_function_call_gateway_is_typed_and_allowlisted(self):
        from travel.tools import TravelTools
        tools = TravelTools(FixtureProvider())
        self.assertEqual(len(tools.invoke("search_pois", {"keyword":"公园", "city":"测试"})["items"]), 2)
        for name, arguments, code in [("delete_file", {}, "unknown_tool"), ("get_route", {"origin":{}, "destination":{}}, "invalid_tool_arguments"), ("search_pois", {"keyword":" ", "city":"测试"}, "invalid_tool_arguments")]:
            with self.assertRaises(TravelFailure) as error:
                tools.invoke(name, arguments)
            self.assertEqual(error.exception.code, code)
        self.assertEqual(len(TravelTools.function_definitions()), 3)

    def test_per_stop_duration_reuses_scheduler(self):
        request = PlanRequest.model_validate({**PAYLOAD, "stay_minutes_by_poi":{"fixture-a":90,"fixture-b":20}})
        trip = plan(request, lambda *_: None, provider=FixtureProvider(), poi_ids_by_day=[["fixture-a","fixture-b"]], optimize_order=False)
        self.assertEqual(trip.days[0].stops[0].departure_time, "10:30")
        self.assertEqual(trip.days[0].stops[1].arrival_time, "11:07")
        self.assertEqual(trip.days[0].stops[1].departure_time, "11:27")
        self.assertEqual(trip.days[0].stops[1].stay_minutes, 20)

    def test_missing_key_never_falls_back(self):
        with self.assertRaises(TravelFailure) as error:
            AmapProvider(AmapClient(key="")).search("公园", "北京")
        self.assertEqual(error.exception.code, "provider_not_configured")

    def test_missing_fields_remain_unknown(self):
        provider = AmapProvider(AmapClient(key="test-only"))
        poi = provider.normalize({"id": "fixture", "name": "TEST ONLY", "location": "116.1,39.9", "biz_ext": {"cost": [], "rating": []}})
        self.assertIsNone(poi.average_spend)
        self.assertIsNone(poi.rating)
        self.assertIsNone(poi.opening_hours)
        self.assertIsNone(provider.normalize({"id": "fixture", "name": "TEST ONLY", "location": "nan,39.9"}))

    def test_bad_transport_data_fails_closed(self):
        origin, destination = FixtureProvider().search()
        provider = AmapProvider(AmapClient(key="test-only"))
        with patch.object(provider, "call", return_value={"route": {"paths": [{"distance": "500"}]}}):
            with self.assertRaises(TravelFailure) as error:
                provider.route(origin, destination, "walking")
        self.assertEqual(error.exception.code, "route_incomplete")

    def test_provider_error_does_not_expose_key(self):
        import httpx
        provider = AmapProvider(AmapClient(key="SECRET-TEST-ONLY"))
        with patch.object(provider.client, "search_poi", side_effect=httpx.ConnectError("https://provider/?key=SECRET-TEST-ONLY")):
            with self.assertRaises(TravelFailure) as error:
                provider.search("x", "y")
        self.assertNotIn("SECRET", str(error.exception))

    def test_existing_scheduler_uses_real_matrix_no_estimate(self):
        from services import route_planner
        request = PlanRequest.model_validate(PAYLOAD)
        with patch.object(route_planner, "_simple_estimate_distance", side_effect=AssertionError("No estimated distances allowed")):
            result = plan(request, lambda *_: None, provider=FixtureProvider())
        self.assertEqual(result.days[0].stops[1].arrival_time, "10:37")
        self.assertIsNone(result.budget.total)
        self.assertEqual(result.budget.status, "unknown")
        self.assertIsNone(result.days[0].stops[0].user_cost)
        self.assertIsNone(result.days[0].stops[0].poi.rating)

    def test_daily_end_is_a_hard_constraint(self):
        request = PlanRequest.model_validate({**PAYLOAD, "day_end": "10:00"})
        with self.assertRaises(TravelFailure) as error:
            plan(request, lambda *_: None, provider=FixtureProvider())
        self.assertEqual(error.exception.code, "time_constraint_exceeded")


class ApiTests(unittest.TestCase):
    def test_edit_constraints_cross_day_moves_and_clear_budget(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory, patch.dict(os.environ, {"TRAVEL_DB_PATH":str(Path(directory)/"test.sqlite3")}), patch("travel.tasks.run", fixture_worker), TestClient(app) as client:
            created=client.post("/api/v1/travel/tasks", json={**PAYLOAD,"days":2,"stops_per_day":1,"budget":100,"user_prices":{"fixture-a":25},"stay_minutes_by_poi":{"fixture-a":90}}).json()
            trip_id=self.wait_task(client, created["id"])["itinerary_id"]
            path=f"/api/v1/travel/itineraries/{trip_id}/adjust"
            invalid=client.post(path,json={"poi_ids_by_day":[["fixture-b"],["fixture-a"]],"day_start":"17:00","day_end":"10:00"})
            self.assertEqual(invalid.status_code,422)
            self.assertEqual(invalid.json()["error"]["code"],"invalid_constraints")
            self.assertEqual(client.post(path,json={"poi_ids_by_day":[["fixture-b"],["fixture-a"]],"stay_minutes_by_poi":{"absent":50}}).status_code,422)
            updated=client.post(path,json={"poi_ids_by_day":[["fixture-b"],["fixture-a"]],"budget":None,"start_date":"2026-10-15","mode":"driving","day_start":"10:00","day_end":"17:00","stay_minutes_by_poi":{"fixture-b":35,"fixture-a":85}})
            self.assertEqual(updated.status_code,202)
            final=self.wait_task(client,updated.json()["id"])
            self.assertEqual(final["status"],"succeeded",final)
            trip=client.get("/api/v1/travel/itineraries/"+final["itinerary_id"]).json()
            self.assertIsNone(trip["budget"]["limit"])
            self.assertEqual(trip["request"]["mode"],"driving")
            self.assertEqual(trip["days"][0]["date"],"2026-10-15")
            self.assertEqual(trip["days"][0]["stops"][0]["poi"]["id"],"fixture-b")
            self.assertEqual(trip["days"][0]["stops"][0]["departure_time"],"10:35")
            self.assertEqual(trip["days"][1]["stops"][0]["user_cost"],25)
            original=client.get("/api/v1/travel/itineraries/"+trip_id).json()
            self.assertEqual(original["budget"]["limit"],100)

    def test_creation_polling_sse_edit_and_persistence(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory, patch.dict(os.environ, {"TRAVEL_DB_PATH": str(Path(directory) / "test.sqlite3")}), patch("travel.tasks.run", fixture_worker):
            with TestClient(app) as client:
                response = client.post("/api/v1/travel/tasks", json=PAYLOAD)
                self.assertEqual(response.status_code, 202)
                identifier = response.json()["id"]
                final = self.wait_task(client, identifier)
                self.assertEqual(final["status"], "succeeded", final)
                trip = client.get("/api/v1/travel/itineraries/" + final["itinerary_id"]).json()
                self.assertEqual(trip["days"][0]["stops"][1]["arrival_time"], "10:37")
                stream = client.get(f"/api/v1/travel/tasks/{identifier}/events/stream").text
                self.assertIn("event: terminal", stream)
                event_list = client.get(f"/api/v1/travel/tasks/{identifier}/events").json()["items"]
                self.assertIn("routing", [event["stage"] for event in event_list])
                self.assertEqual(client.get(f"/api/v1/travel/tasks/{identifier}/events?after={event_list[-1]['id']}").json()["items"], [])
                edited = client.post(f"/api/v1/travel/itineraries/{trip['id']}/adjust", json={
                    "poi_ids_by_day": [["fixture-b", "fixture-a"]], "user_prices": {"fixture-b": 88}, "stay_minutes": 45,
                })
                self.assertEqual(edited.status_code, 202)
                final_edit = self.wait_task(client, edited.json()["id"])
                adjusted = client.get("/api/v1/travel/itineraries/" + final_edit["itinerary_id"]).json()
                self.assertEqual(adjusted["parent_id"], trip["id"])
                self.assertEqual(adjusted["days"][0]["stops"][0]["poi"]["id"], "fixture-b")
                self.assertEqual(adjusted["budget"]["known_subtotal"], 88)
                self.assertEqual(len(client.get("/api/v1/travel/itineraries").json()["items"]), 2)
            with TestClient(app) as client:
                self.assertEqual(client.get(f"/api/v1/travel/tasks/{identifier}").json()["status"], "succeeded")
                self.assertEqual(len(client.get("/api/v1/travel/itineraries").json()["items"]), 2)

    def wait_task(self, client, identifier):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            task = client.get(f"/api/v1/travel/tasks/{identifier}").json()
            if task["status"] not in {"queued", "running"}:
                return task
            # Verify another endpoint remains responsive while worker runs.
            self.assertEqual(client.get("/api/v1/travel/capabilities").status_code, 200)
            time.sleep(0.1)
        self.fail("Worker did not terminate")

    def test_structured_errors_and_production_boundary(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory, patch.dict(os.environ, {"TRAVEL_DB_PATH": str(Path(directory)/"test.sqlite3"), "TRAVEL_PRODUCTION": "1"}), TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/travel/tasks/missing").json()["error"]["code"], "task_not_found")
            invalid = client.post("/api/v1/travel/tasks", json={**PAYLOAD, "day_end": "08:00"})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["error"]["code"], "validation_error")
            self.assertEqual(client.post("/api/route/generate", json={"query":"fixture"}).status_code, 410)


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_cancel_and_queue_limit_terminate_workers(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory, patch("travel.tasks.run", stalled_worker):
            store = Store(Path(directory)/"test.sqlite3")
            manager = TaskManager(store, timeout=0.5, concurrency=1, capacity=1)
            task = manager.create({"request": PAYLOAD})
            with self.assertRaises(TravelFailure):
                manager.create({"request": PAYLOAD})
            await asyncio.sleep(0.8)
            self.assertEqual(store.task(task.id).status, "timed_out")
            await manager.close()
            self.assertFalse(manager.processes)
            manager = TaskManager(store, timeout=10)
            task = manager.create({"request": PAYLOAD})
            await asyncio.sleep(0.2)
            manager.cancel(task.id)
            await manager.close()
            self.assertEqual(store.task(task.id).status, "cancelled")
            self.assertFalse(manager.processes)
            store.close()

    async def test_restart_marks_unfinished_tasks(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as directory:
            store = Store(Path(directory)/"test.sqlite3")
            store.put_task(Task(id="interrupted", status="running"))
            manager = TaskManager(store)
            self.assertEqual(store.task("interrupted").error.code, "service_restarted")
            await manager.close()
            store.close()


if __name__ == "__main__":
    (ROOT / ".tmp").mkdir(exist_ok=True)
    unittest.main()
