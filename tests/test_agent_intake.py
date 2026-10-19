"""Isolated model replies through the real SDK/HelloAgents; never a fallback."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from agent.travel_intake import create_draft, status, validate_submission
from agent.travel_tool_bridge import online_registry
from travel.provider import AmapClient, AmapProvider, TravelFailure
from travel.schemas import DraftRequest

TEXT="TEST ONLY 10月20日去杭州玩两天，博物馆，步行，预算800元，需要预约"
ARGS={"values":{"city":"杭州","query":"博物馆","start_date":"2026-10-20","days":2,"mode":"walking","budget":800},
      "evidence":{"city":"杭州","query":"博物馆","start_date":"10月20日","days":"两天","mode":"步行","budget":"预算800元"},
      "unhandled_requirements":["需要预约"]}
PAYLOAD={"text":TEXT,"reference_date":"2026-10-11"}


class FixtureLLM:
    def __init__(self, arguments=None, name="submit_draft", *, duplicate=False, free_text=False, network_error=False):
        self.model,self.provider,self.temperature,self.max_tokens="test-only","custom",0,1600
        self.calls=0
        def respond(request):
            self.calls+=1
            if network_error:
                raise httpx.ConnectError("TEST ONLY secret API token upstream URL",request=request)
            body=json.loads(request.content)
            self.schemas=body["tools"]
            self.messages=body["messages"]
            tool={"id":"test-call","type":"function","function":{"name":name,"arguments":json.dumps(arguments if arguments is not None else ARGS)}}
            calls=[] if free_text else [tool]
            if duplicate:
                calls.append({**tool,"id":"test-call-2"})
            return httpx.Response(200,json={"id":"test-only-response","object":"chat.completion","model":"test-only","created":0,
                "choices":[{"index":0,"message":{"role":"assistant","content":"TEST ONLY invented POI free text must be ignored","tool_calls":calls},"finish_reason":"stop"}]})
        self._client=OpenAI(api_key="TEST_ONLY_NOT_A_REAL_KEY",base_url="https://test.invalid/v1",max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(respond)))


def draft_fixture_worker(payload, output):
    result=create_draft(DraftRequest.model_validate(payload["request"]),lambda stage,message:output.put({"kind":"event","stage":stage,"message":message}),llm=FixtureLLM())
    output.put({"kind":"result","data":result.model_dump(mode="json")})


class AgentTests(unittest.TestCase):
    def test_real_framework_function_call_and_existing_coordinator(self):
        llm=FixtureLLM()
        events=[]
        result=create_draft(DraftRequest.model_validate(PAYLOAD),lambda stage,message:events.append(stage),llm=llm)
        self.assertEqual(llm.calls,1)
        self.assertTrue(llm._client.is_closed())
        self.assertEqual(result.proposal.values.city,"杭州")
        self.assertEqual(result.coordinator_action,"continue")
        self.assertEqual(len(llm.schemas),1)
        self.assertEqual(llm.schemas[0]["function"]["name"],"submit_draft")
        self.assertEqual(result.proposal.unhandled_requirements,["需要预约"])
        self.assertNotIn("invented POI",result.model_dump_json())
        self.assertIn("coordinator",events)

    def test_missing_fields_require_clarification(self):
        llm=FixtureLLM({"values":{},"evidence":{}})
        result=create_draft(DraftRequest.model_validate(PAYLOAD),lambda *_:None,llm=llm)
        self.assertEqual(result.coordinator_action,"ask_clarification")
        self.assertEqual(len(result.questions),3)

    def test_untrusted_model_output_and_tool_selection_fail_closed(self):
        cases=[(FixtureLLM({**ARGS,"values":{**ARGS["values"],"poi_ids":["invented"]}}),"invalid_agent_output"),
               (FixtureLLM({**ARGS,"evidence":{**ARGS["evidence"],"city":"上海"}}),"ungrounded_agent_output"),
               (FixtureLLM(name="search_pois"),"unknown_tool"), (FixtureLLM(duplicate=True),"duplicate_draft_submission"),
               (FixtureLLM(free_text=True),"missing_draft_submission"),(FixtureLLM(network_error=True),"llm_call_failed")]
        for llm,code in cases:
            with self.subTest(code=code),self.assertRaises(TravelFailure) as error:
                create_draft(DraftRequest.model_validate(PAYLOAD),lambda *_:None,llm=llm)
            self.assertEqual(error.exception.code,code)
            self.assertNotIn("secret",str(error.exception))
            self.assertEqual(llm.calls,1)

    def test_disabled_or_missing_model_has_no_local_fallback(self):
        for enabled,expected in [("0","agent_disabled"),("1","llm_not_configured")]:
            with patch.dict(os.environ,{"TRAVEL_AGENT_ENABLED":enabled,"LLM_INTENT_DISABLE_LLM":"0","TRAVEL_LLM_API_KEY":"","OPENAI_API_KEY":"","DASHSCOPE_API_KEY":""}),self.assertRaises(TravelFailure) as error:
                create_draft(DraftRequest.model_validate(PAYLOAD),lambda *_:None)
            self.assertEqual(error.exception.code,expected)

    def test_original_registry_bridge_returns_sanitized_real_data_failure_and_budget(self):
        registry=online_registry(AmapProviderGateway(),max_calls=1)
        result=registry.run("search_pois",keyword="公园",city="北京")
        self.assertEqual(result.status,"failed")
        self.assertEqual(result.error,"provider_not_configured")
        self.assertFalse(result.fallback_used)
        self.assertEqual(registry.run("search_pois",keyword="公园",city="北京").error,"tool_budget_exhausted")
        self.assertEqual(registry.run("shell",command="x").status,"skipped")

    def test_draft_task_sse_persistence_and_no_itinerary_created(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as directory,patch.dict(os.environ,{"TRAVEL_DB_PATH":str(Path(directory)/"test.sqlite3")}),patch("travel.tasks.run",draft_fixture_worker):
            with TestClient(app) as client:
                created=client.post("/api/v1/travel/drafts",json=PAYLOAD)
                self.assertEqual(created.status_code,202)
                task=created.json()
                self.assertEqual(task["kind"],"draft")
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    final=client.get("/api/v1/travel/tasks/"+task["id"]).json()
                    if final["status"] not in {"queued","running"}: break
                    time.sleep(0.1)
                self.assertEqual(final["status"],"succeeded",final)
                self.assertIsNone(final["itinerary_id"])
                draft_id=final["draft_id"]
                self.assertEqual(client.get("/api/v1/travel/drafts/"+draft_id).json()["proposal"]["values"]["budget"],800)
                self.assertIn("event: terminal",client.get("/api/v1/travel/tasks/"+task["id"]+"/events/stream").text)
                self.assertEqual(client.get("/api/v1/travel/itineraries").json()["items"],[])
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/v1/travel/drafts/"+draft_id).status_code,200)


def AmapProviderGateway():
    from travel.tools import TravelTools
    return TravelTools(AmapProvider(AmapClient(key="")))


if __name__=="__main__":
    unittest.main()
