"""Isolated draft edits: no model/provider calls or production records."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from agent.travel_intake import finish_draft
from travel.drafts import clarify
from travel.provider import TravelFailure
from travel.schemas import Draft, DraftClarificationRequest, DraftRequest, DraftSubmission, Task
from travel.store import Store


def partial_draft():
    return finish_draft(DraftRequest(text="TEST ONLY 想逛博物馆，需要预约", reference_date="2026-10-16"),
        DraftSubmission(values={"query":"博物馆"}, evidence={"query":"博物馆"}, unhandled_requirements=["需要预约"]), lambda *_: None)


class ClarificationTests(unittest.TestCase):
    def test_same_id_multiple_rounds_confirmation_clear_and_restart(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as directory, patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(directory)/"draft.sqlite3")}), patch("agent.travel_intake.create_draft",side_effect=AssertionError("No model call")), patch("travel.tools.TravelTools",side_effect=AssertionError("No data call")):
            with TestClient(app) as client:
                store=app.state.travel.store
                seed=partial_draft()
                store.succeed_draft(Task(id="test-only-task",status="running",kind="draft"),seed)
                url="/api/v1/travel/drafts/"+seed.id
                first=client.patch(url,json={"expected_revision":1,"values":{"city":"杭州","budget":0},"confirm_fields":["query"]})
                self.assertEqual(first.status_code,200,first.text)
                result=first.json()
                self.assertEqual(result["id"],seed.id)
                self.assertEqual(result["revision"],2)
                self.assertEqual(result["confirmed_fields"],["budget","city","query"])
                self.assertEqual(result["questions"],["请确认出发日期"])
                self.assertEqual(result["field_sources"]["city"],"user_input")
                self.assertNotIn("query",result["field_sources"])
                second=client.patch(url,json={"expected_revision":2,"values":{"start_date":"2026-10-20"}}).json()
                self.assertEqual(second["revision"],3)
                self.assertEqual(second["proposal"]["values"]["city"],"杭州")
                self.assertEqual(second["proposal"]["values"]["budget"],0)
                self.assertEqual(second["proposal"]["evidence"]["query"],"博物馆")
                self.assertEqual(second["questions"],[])
                self.assertEqual(second["proposal"]["unhandled_requirements"],["需要预约"])
                cleared=client.patch(url,json={"expected_revision":3,"values":{"city":None}}).json()
                self.assertEqual(cleared["revision"],4)
                self.assertEqual(cleared["questions"],["请填写目的地城市"])
                self.assertNotIn("city",cleared["confirmed_fields"])
                self.assertNotIn("city",cleared["proposal"]["evidence"])
                self.assertEqual(len(cleared["clarifications"]),3)
                self.assertEqual(cleared["clarifications"][0]["values"],{"city":"杭州","budget":0})
                self.assertEqual(len(store.tasks()),1)  # No new task or itinerary.
                self.assertEqual(client.get("/api/v1/travel/itineraries").json()["items"],[])
            with TestClient(app) as client:
                self.assertEqual(client.get(url).json(),cleared)

    def test_validation_and_conflict_leave_current_draft_unchanged(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as directory, patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(directory)/"draft.sqlite3")}):
            with TestClient(app) as client:
                seed=partial_draft()
                app.state.travel.store.succeed_draft(Task(id="test-only-task",status="running",kind="draft"),seed)
                url="/api/v1/travel/drafts/"+seed.id
                for body in ({"expected_revision":1}, {"expected_revision":1,"values":{"poi_ids":["fake"]}},
                    {"expected_revision":1,"values":{"days":99}}, {"expected_revision":1,"confirm_fields":["city"]},
                    {"expected_revision":1,"confirm_fields":["query","query"]},
                    {"expected_revision":1,"values":{"day_start":"18:00","day_end":"09:00"}}):
                    with self.subTest(body=body):
                        self.assertEqual(client.patch(url,json=body).status_code,422)
                        self.assertEqual(client.get(url).json()["revision"],1)
                body={"expected_revision":1,"values":{"day_start":"10:00","day_end":"18:00"}}
                self.assertEqual(client.patch(url,json=body).status_code,200)
                stale=client.patch(url,json={"expected_revision":1,"values":{"city":"上海"}})
                self.assertEqual(stale.status_code,409)
                self.assertEqual(stale.json()["error"]["code"],"draft_revision_conflict")
                current=client.get(url).json()
                self.assertIsNone(current["proposal"]["values"]["city"])
                bad_merged=client.patch(url,json={"expected_revision":2,"values":{"day_end":"09:00"}})
                self.assertEqual(bad_merged.status_code,422)
                self.assertEqual(client.get(url).json(),current)
                self.assertEqual(client.patch("/api/v1/travel/drafts/absent",json=body).status_code,404)

    def test_store_competing_writer_cannot_overwrite_revision(self):
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as directory:
            path=Path(directory)/"draft.sqlite3"
            a,b=Store(path),Store(path)
            try:
                seed=partial_draft()
                a.succeed_draft(Task(id="test-only-task",status="running",kind="draft"),seed)
                one=clarify(a.draft(seed.id),DraftClarificationRequest(expected_revision=1,values={"city":"杭州"}))
                two=clarify(b.draft(seed.id),DraftClarificationRequest(expected_revision=1,values={"city":"上海"}))
                a.update_draft(one,1)
                with self.assertRaises(TravelFailure) as error: b.update_draft(two,1)
                self.assertEqual(error.exception.code,"draft_revision_conflict")
                self.assertEqual(b.draft(seed.id).proposal.values.city,"杭州")
            finally:
                a.close(); b.close()

    def test_old_saved_draft_uses_defaults_without_losing_original(self):
        seed=partial_draft()
        old=seed.model_dump(mode="json",exclude={"revision","updated_at","confirmed_fields","field_sources","clarifications"})
        restored=Draft.model_validate_json(json.dumps(old))
        self.assertEqual(restored.revision,1)
        self.assertEqual(restored.confirmed_fields,[])
        self.assertEqual(restored.proposal.evidence,seed.proposal.evidence)


if __name__=="__main__":
    unittest.main()
