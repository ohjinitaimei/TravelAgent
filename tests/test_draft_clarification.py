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
from travel.schemas import Draft, DraftClarificationRequest, DraftRequest, DraftSubmission, DraftValues, Task
from pydantic import ValidationError
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
                self.assertEqual(result["field_sources"]["query"],"model_extracted")
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

    def test_partial_daily_expressions_preserve_unknowns_and_require_explicit_completion(self):
        seed=partial_draft()
        request=DraftClarificationRequest(expected_revision=1,values={"days":2,
            "day_schedules":[{"day_start":"14:00"},{"day_end":"16:30","stay_minutes":45}],
            "max_leg_travel_minutes":30,"max_daily_travel_minutes":90,
            "origin_hint":"TEST ONLY 酒店","destination_hint":"TEST ONLY 车站"})
        result=clarify(seed,request)
        self.assertIsNone(result.proposal.values.day_schedules[0].day_end)
        self.assertIsNone(result.proposal.values.day_schedules[0].stay_minutes)
        self.assertIsNone(result.proposal.values.day_schedules[1].day_start)
        self.assertIn("请补全第 1 天的结束时间、默认停留",result.questions)
        self.assertIn("请补全第 2 天的开始时间",result.questions)
        self.assertTrue(any("真实地点搜索" in item and "酒店" in item for item in result.questions))
        self.assertEqual(result.coordinator_action,"ask_clarification")
        self.assertEqual(result.field_sources["day_schedules"],"user_input")
        self.assertIn("交通上限", " ".join(result.warnings))
        history=Draft.model_validate_json(result.model_dump_json()).clarifications[-1]
        self.assertEqual(history.values["day_schedules"][0].day_start,"14:00")
        self.assertIsNone(history.values["day_schedules"][0].day_end)
        complete=clarify(result,DraftClarificationRequest(expected_revision=2,values={
            "city":"杭州","start_date":"2026-10-25",
            "day_schedules":[{"day_start":"14:00","day_end":"18:00","stay_minutes":60},
                {"day_start":"09:00","day_end":"16:30","stay_minutes":45}]}))
        self.assertFalse(any("补全第" in item for item in complete.questions))
        self.assertEqual(complete.proposal.values.max_leg_travel_minutes,30)
        self.assertEqual(complete.proposal.values.origin_hint,"TEST ONLY 酒店")
        self.assertTrue(any("真实地点搜索" in item for item in complete.questions))
        self.assertIsNone(complete.proposal.values.day_start)  # No inferred shared fallback.

    def test_daily_length_conflict_requires_atomic_revision_and_legacy_fields_remain(self):
        seed=clarify(partial_draft(),DraftClarificationRequest(expected_revision=1,values={
            "days":2,"day_schedules":[{"day_start":"14:00"},{"day_start":"09:00"}]}))
        with self.assertRaises(TravelFailure) as error:
            clarify(seed,DraftClarificationRequest(expected_revision=2,values={"days":1}))
        self.assertEqual(error.exception.code,"invalid_draft_constraints")
        self.assertEqual(seed.revision,2)
        self.assertEqual(len(seed.proposal.values.day_schedules),2)
        changed=clarify(seed,DraftClarificationRequest(expected_revision=2,values={"days":1,"day_schedules":[{"day_start":"14:00"}]}))
        self.assertEqual(changed.revision,3)
        self.assertEqual(changed.proposal.values.days,1)
        self.assertEqual(len(changed.proposal.values.day_schedules),1)
        unknown=finish_draft(seed.input,DraftSubmission(values={"day_schedules":[{"day_end":"17:00"}]},evidence={"day_schedules":"TEST ONLY"}),lambda *_:None)
        self.assertIsNone(unknown.proposal.values.days)
        self.assertIn("请确认旅行天数，以核对逐日时段数量",unknown.questions)

    def test_new_fields_clear_and_confirm_without_implicit_providers(self):
        result=clarify(partial_draft(),DraftClarificationRequest(expected_revision=1,values={
            "day_schedules":[{"day_start":"10:00"}],"max_leg_travel_minutes":20,"origin_hint":"TEST ONLY 酒店"}))
        confirmed=clarify(result,DraftClarificationRequest(expected_revision=2,confirm_fields=["origin_hint","day_schedules"]))
        self.assertEqual(confirmed.proposal.values.origin_hint,"TEST ONLY 酒店")
        self.assertEqual(confirmed.field_sources["origin_hint"],"user_input")
        self.assertTrue(any("真实地点搜索" in item for item in confirmed.questions))
        cleared=clarify(confirmed,DraftClarificationRequest(expected_revision=3,values={
            "day_schedules":None,"origin_hint":None,"max_leg_travel_minutes":None}))
        for field in ("day_schedules","origin_hint","max_leg_travel_minutes"):
            self.assertNotIn(field,cleared.confirmed_fields)
            self.assertNotIn(field,cleared.field_sources)
            self.assertNotIn(field,cleared.proposal.evidence)
        self.assertEqual(cleared.proposal.values.query,"博物馆")

    def test_new_fields_reject_coercion_invented_poi_payloads_and_invalid_windows(self):
        cases=[{"max_leg_travel_minutes":True},{"max_daily_travel_minutes":"30"},{"max_daily_travel_minutes":1440},
            {"day_schedules":[]},{"day_schedules":[{"stay_minutes":30.5}]},
            {"day_schedules":[{"day_start":"18:00","day_end":"09:00"}]},
            {"days":2,"day_schedules":[{}]}, {"origin_hint":{"id":"invented","longitude":120}},
            {"destination_hint":" "},{"origin_poi_id":"invented"},
            {"day_schedules":[{"day_start":"10:00","poi_id":"invented"}]}]
        for values in cases:
            with self.subTest(values=values),self.assertRaises(ValidationError):
                DraftValues.model_validate(values)

    def test_new_daily_fields_survive_api_restart_and_bad_merge_keeps_saved_revision(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as directory, patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(directory)/"draft.sqlite3")}), patch("agent.travel_intake.create_draft",side_effect=AssertionError("No model call")), patch("travel.tools.TravelTools",side_effect=AssertionError("No data call")):
            with TestClient(app) as client:
                seed=partial_draft()
                app.state.travel.store.succeed_draft(Task(id="test-only-task",status="running",kind="draft"),seed)
                url="/api/v1/travel/drafts/"+seed.id
                response=client.patch(url,json={"expected_revision":1,"values":{"days":2,
                    "day_schedules":[{"day_start":"14:00"},{"day_end":"16:00"}],
                    "max_daily_travel_minutes":75,"origin_hint":"TEST ONLY 酒店"}})
                self.assertEqual(response.status_code,200,response.text)
                saved=response.json()
                bad=client.patch(url,json={"expected_revision":2,"values":{"days":1}})
                self.assertEqual(bad.status_code,422)
                self.assertEqual(bad.json()["error"]["code"],"invalid_draft_constraints")
                self.assertEqual(client.get(url).json(),saved)
            with TestClient(app) as client:
                self.assertEqual(client.get(url).json(),saved)
                self.assertEqual(client.get("/api/v1/travel/itineraries").json()["items"],[])


if __name__=="__main__":
    unittest.main()
