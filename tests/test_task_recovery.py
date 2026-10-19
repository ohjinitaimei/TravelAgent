"""Task receipts and retries, using isolated fixtures and databases only."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from fastapi.testclient import TestClient
from test_travel import fixture_worker, PAYLOAD
from travel.schemas import Error, Task


class RecoveryTests(unittest.TestCase):
    def wait(self,client,identifier):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            task=client.get("/api/v1/travel/tasks/"+identifier).json()
            if task["status"] not in {"queued","running"}: return task
            time.sleep(.05)
        self.fail("Task did not reach a terminal state")

    def test_receipt_deduplicates_conflicting_payload_and_survives_restart(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder,patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(folder)/"test.sqlite3")}),patch("travel.tasks.run",fixture_worker):
            key={"Idempotency-Key":"test-only-receipt"}
            with TestClient(app) as client:
                first=client.post("/api/v1/travel/tasks",json=PAYLOAD,headers=key)
                self.assertEqual(first.status_code,202)
                identifier=first.json()["id"]
                self.assertEqual(client.post("/api/v1/travel/tasks",json=PAYLOAD,headers=key).json()["id"],identifier)
                conflict=client.post("/api/v1/travel/tasks",json={**PAYLOAD,"budget":99},headers=key)
                self.assertEqual(conflict.status_code,409)
                self.assertEqual(conflict.json()["error"]["code"],"idempotency_conflict")
                self.assertEqual(client.get("/api/v1/travel/submissions/test-only-receipt").json()["id"],identifier)
                final=self.wait(client,identifier)
                self.assertEqual(final["status"],"succeeded",final)
                self.assertEqual(len(app.state.travel.store.tasks()),1)
                self.assertEqual(client.post(f"/api/v1/travel/tasks/{identifier}/retry").status_code,409)
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/v1/travel/tasks",json=PAYLOAD,headers=key).json()["id"],identifier)
                self.assertEqual(len(client.get("/api/v1/travel/itineraries").json()["items"]),1)

    def test_retry_retains_payload_and_original_terminal_record(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder,patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(folder)/"test.sqlite3")}),patch("travel.tasks.run",fixture_worker),TestClient(app) as client:
            task=client.post("/api/v1/travel/tasks",json=PAYLOAD).json()
            source=app.state.travel.store.task_request(task["id"])
            cancelled=client.post(f"/api/v1/travel/tasks/{task['id']}/cancel").json()
            self.assertTrue(cancelled["retry_available"])
            headers={"Idempotency-Key":"test-only-retry"}
            retry=client.post(f"/api/v1/travel/tasks/{task['id']}/retry",headers=headers)
            self.assertEqual(retry.status_code,202,retry.text)
            new=retry.json()
            self.assertNotEqual(new["id"],task["id"])
            self.assertEqual(new["retry_of"],task["id"])
            self.assertEqual(client.post(f"/api/v1/travel/tasks/{task['id']}/retry",headers=headers).json()["id"],new["id"])
            self.assertEqual(app.state.travel.store.task_request(new["id"]),source)
            self.assertEqual(self.wait(client,new["id"])["status"],"succeeded")
            self.assertEqual(client.get(f"/api/v1/travel/tasks/{task['id']}").json()["status"],"cancelled")

    def test_retryable_failure_and_old_task_without_payload(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder,patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(folder)/"test.sqlite3")}),patch("travel.tasks.run",fixture_worker),TestClient(app) as client:
            old=Task(id="test-only-old",status="failed",error=Error(code="worker_exited",message="TEST ONLY",retryable=True))
            app.state.travel.store.put_task(old)
            self.assertEqual(client.post("/api/v1/travel/tasks/test-only-old/retry").status_code,409)
            task=client.post("/api/v1/travel/tasks",json=PAYLOAD).json()
            app.state.travel.finish(task["id"],"failed",Error(code="provider_timeout",message="TEST ONLY",retryable=True))
            self.assertTrue(client.get(f"/api/v1/travel/tasks/{task['id']}").json()["retry_available"])
            retry=client.post(f"/api/v1/travel/tasks/{task['id']}/retry").json()
            self.assertEqual(self.wait(client,retry["id"])["status"],"succeeded")
            self.assertEqual(client.get("/api/v1/travel/submissions/unknown-key").status_code,404)
            self.assertEqual(client.post("/api/v1/travel/tasks",json=PAYLOAD,headers={"Idempotency-Key":"bad"}).status_code,422)


if __name__=="__main__":
    (ROOT/".tmp").mkdir(exist_ok=True)
    unittest.main()
