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
from agent.travel_intake import create_draft, status, validate_submission, reference_calendar
from agent.travel_tool_bridge import online_registry
from travel.provider import AmapClient, AmapProvider, TravelFailure
from travel.schemas import DraftRequest

TEXT="TEST ONLY 10月20日去杭州玩两天，博物馆，步行，预算800元，需要预约"
ARGS={"values":{"city":"杭州","query":"博物馆","start_date":"2026-10-20","days":2,"mode":"walking","budget":800},
      "evidence":{"city":"杭州","query":"博物馆","start_date":"10月20日","days":"两天","mode":"步行","budget":"预算800元"},
      "unhandled_requirements":["需要预约"]}
PAYLOAD={"text":TEXT,"reference_date":"2026-10-11"}


class FixtureLLM:
    def __init__(self, arguments=None, name="submit_draft", *, duplicate=False, free_text=False, network_error=False, error_status=None):
        self.model,self.provider,self.temperature,self.max_tokens="test-only","custom",0,1600
        self.calls=0
        def respond(request):
            self.calls+=1
            if network_error:
                raise httpx.ConnectError("TEST ONLY secret API token upstream URL",request=request)
            if error_status is not None:
                return httpx.Response(error_status,json={'error':{'message':'TEST_ONLY_PRIVATE_TOKEN https://private.invalid/secret'}})
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
    def test_calendar_context_uses_reference_across_year_and_leap_boundaries_without_filling_values(self):
        from datetime import date
        for reference,tomorrow in (('2026-12-31','2027-01-01'),('2028-02-28','2028-02-29'),('2028-02-29','2028-03-01')):
            llm=FixtureLLM({'values':{},'evidence':{}})
            request=DraftRequest(text='TEST ONLY 日期尚未决定',reference_date=reference)
            draft=create_draft(request,lambda *_:None,llm=llm)
            message=json.loads(next(message['content'] for message in llm.messages if message['role']=='user'))
            with self.subTest(reference=reference):
                self.assertEqual(message['reference_calendar']['今天'],reference)
                self.assertEqual(message['reference_calendar']['明天'],tomorrow)
                self.assertEqual(message['user_text'],request.text)
                self.assertEqual(message['timezone'],'Asia/Shanghai')
                self.assertIsNone(draft.proposal.values.start_date)
                self.assertNotIn('start_date',draft.proposal.evidence)
                self.assertEqual(llm.calls,1)
        self.assertEqual(reference_calendar(date.max),{'今天':'9999-12-31'})

    def test_model_service_failures_have_safe_actionable_messages_and_no_sdk_retry(self):
        for status,message,retryable in ((401,'授权未通过',False),(403,'授权未通过',False),
                (400,'拒绝了需求整理请求',False),(429,'限制调用',True),(500,'模型调用失败',True)):
            llm=FixtureLLM(error_status=status)
            with self.subTest(status=status),self.assertRaises(TravelFailure) as caught:
                create_draft(DraftRequest.model_validate(PAYLOAD),lambda *_:None,llm=llm)
            self.assertEqual(caught.exception.code,'llm_call_failed')
            self.assertIn(message,caught.exception.message)
            self.assertEqual(caught.exception.retryable,retryable)
            self.assertNotIn('PRIVATE',caught.exception.message)
            self.assertNotIn('private.invalid',caught.exception.message)
            self.assertEqual(llm.calls,1)
            self.assertTrue(llm._client.is_closed())

    def test_review_cases_cross_real_framework_without_defaults_or_automatic_confirmation(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from live_requirements_cases import REVIEW_SCENARIOS,scenario,validate_initial
        for name in REVIEW_SCENARIOS:
            case=scenario(name,'杭州','2027-01-03',reference='2026-12-31')
            arguments={'values':case['expected'],
                'evidence':{field:case['text'] for field,value in case['expected'].items() if value is not None},
                'unhandled_requirements':case['required_unhandled']}
            llm=FixtureLLM(arguments);events=[]
            with self.subTest(name=name):
                result=create_draft(DraftRequest(text=case['text'],reference_date='2026-12-31'),lambda stage,_:events.append(stage),llm=llm)
                validate_initial(result.model_dump(mode='json'),case,name)
                self.assertEqual(llm.calls,1)
                self.assertTrue(llm._client.is_closed())
                self.assertEqual(events.count('agent_call'),1)
                self.assertEqual(events.count('draft_validated'),1)
                self.assertEqual(result.confirmed_fields,[])

    def test_evidence_value_types_fail_without_coercion_or_silent_dropping(self):
        for evidence in ({'city':None},{'city':['杭州']},{'city':{'quote':'杭州'}}):
            llm=FixtureLLM({'values':{'city':'杭州'},'evidence':evidence})
            with self.subTest(evidence_type=type(evidence['city']).__name__),self.assertRaises(TravelFailure) as failure:
                create_draft(DraftRequest.model_validate(PAYLOAD),lambda *_:None,llm=llm)
            self.assertEqual(failure.exception.code,'invalid_agent_output')
            self.assertEqual(failure.exception.draft_validation.issues[0].path,'evidence')
            self.assertEqual(failure.exception.draft_validation.issues[0].reason,'type')
            self.assertEqual(llm.calls,1)

    def test_partial_unknowns_with_sparse_string_evidence_keep_nulls(self):
        text='TEST ONLY 杭州博物馆，两天，第一天14点开始，第二天16点结束'
        arguments={'values':{'city':'杭州','query':'博物馆','days':2,'budget':None,'mode':None,
            'day_schedules':[{'day_start':'14:00','day_end':None,'stay_minutes':None},{'day_start':None,'day_end':'16:00','stay_minutes':None}]},
            'evidence':{'city':'杭州','query':'博物馆','days':'两天','day_schedules':'第一天14点开始，第二天16点结束'}}
        llm=FixtureLLM(arguments)
        result=create_draft(DraftRequest(text=text,reference_date='2026-10-24'),lambda *_:None,llm=llm)
        self.assertIsNone(result.proposal.values.mode)
        self.assertIsNone(result.proposal.values.budget)
        self.assertIsNone(result.proposal.values.day_schedules[0].day_end)
        self.assertNotIn('budget',result.proposal.evidence)
        self.assertEqual(result.confirmed_fields,[])
        self.assertEqual(llm.calls,1)

    def test_worker_serializes_safe_diagnostics_and_grounding_uses_same_contract(self):
        from queue import Queue
        from travel.worker import run
        original=create_draft
        output=Queue()
        with patch('agent.travel_intake.create_draft',lambda request,emit:original(request,emit,llm=FixtureLLM({'values':{'days':True},'evidence':{}}))):
            run({'kind':'draft','request':PAYLOAD},output)
        records=[]
        while not output.empty():records.append(output.get_nowait())
        error=next(record['data'] for record in records if record['kind']=='error')
        self.assertEqual(error['draft_validation'],{'issues':[{'path':'values.days','reason':'type'}]})
        self.assertFalse(error['retryable'])
        self.assertFalse(any(record['kind']=='result' for record in records))
        with self.assertRaises(TravelFailure) as failure:
            validate_submission(DraftRequest.model_validate(PAYLOAD),{'values':{'city':'杭州'},'evidence':{'city':'PRIVATE_NOT_IN_TEXT'}})
        self.assertEqual(failure.exception.draft_validation.issues[0].reason,'ungrounded')
        self.assertNotIn('PRIVATE',failure.exception.draft_validation.model_dump_json())

    def test_diagnostics_limit_and_old_errors_remain_readable(self):
        from travel.schemas import DraftValues, Error
        arguments={'values':{key:[] for key in DraftValues.model_fields},'evidence':{}}
        with self.assertRaises(TravelFailure) as error:
            validate_submission(DraftRequest.model_validate(PAYLOAD),arguments)
        self.assertEqual(len(error.exception.draft_validation.issues),8)
        self.assertIsNone(Error.model_validate({'code':'old_error','message':'旧任务'}).draft_validation)

    def test_rejection_diagnostics_are_bounded_and_never_echo_model_data(self):
        marker='TEST_ONLY_PRIVATE_ENDPOINT_OR_INPUT'
        arguments={'values':{'day_schedules':[{'day_start':marker,'stay_minutes':True}],marker:marker},'evidence':{}}
        with self.assertRaises(TravelFailure) as error:
            validate_submission(DraftRequest.model_validate(PAYLOAD),arguments)
        details=error.exception.draft_validation
        self.assertNotIn(marker,details.model_dump_json())
        self.assertIn({'path':'values.day_schedules.0.day_start','reason':'format'},details.model_dump()['issues'])
        self.assertIn({'path':'values.day_schedules.0.stay_minutes','reason':'type'},details.model_dump()['issues'])
        self.assertLessEqual(len(details.issues),8)

    def test_real_framework_preserves_safe_rejection_and_emits_one_event_without_retry(self):
        llm=FixtureLLM({'values':{'days':True},'evidence':{}})
        events=[]
        with self.assertRaises(TravelFailure) as error:
            create_draft(DraftRequest.model_validate(PAYLOAD),lambda stage,message:events.append((stage,message)),llm=llm)
        self.assertEqual(error.exception.draft_validation.model_dump(),{'issues':[{'path':'values.days','reason':'type'}]})
        self.assertEqual(sum(stage=='draft_rejected' for stage,_ in events),1)
        self.assertEqual(llm.calls,1)
        self.assertTrue(llm._client.is_closed())

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

    def test_same_function_call_extracts_daily_limits_and_literal_endpoint_hints(self):
        text="TEST ONLY 杭州博物馆，两天，10月25日，第一天14点开始，第二天16点结束，每段最多30分钟，每天交通90分钟，从杭州东站出发，回西湖酒店"
        arguments={"values":{"city":"杭州","query":"博物馆","days":2,"start_date":"2026-10-25",
            "day_schedules":[{"day_start":"14:00"},{"day_end":"16:00"}],
            "max_leg_travel_minutes":30,"max_daily_travel_minutes":90,"origin_hint":"杭州东站","destination_hint":"西湖酒店"},
            "evidence":{"city":"杭州","query":"博物馆","days":"两天","start_date":"10月25日",
                "day_schedules":"第一天14点开始，第二天16点结束","max_leg_travel_minutes":"每段最多30分钟",
                "max_daily_travel_minutes":"每天交通90分钟","origin_hint":"杭州东站","destination_hint":"西湖酒店"}}
        llm=FixtureLLM(arguments)
        result=create_draft(DraftRequest(text=text,reference_date="2026-10-22"),lambda *_:None,llm=llm)
        self.assertEqual(llm.calls,1)
        self.assertEqual(result.proposal.values.day_schedules[0].day_start,"14:00")
        self.assertIsNone(result.proposal.values.day_schedules[0].day_end)
        self.assertEqual(result.proposal.values.max_leg_travel_minutes,30)
        self.assertEqual(result.proposal.values.max_daily_travel_minutes,90)
        self.assertEqual(result.field_sources["day_schedules"],"model_extracted")
        self.assertEqual(result.field_sources["origin_hint"],"model_extracted")
        self.assertEqual(result.confirmed_fields,[])
        self.assertTrue(any("真实地点搜索" in question for question in result.questions))
        tool_schema=llm.schemas[0]["function"]["parameters"]
        values=tool_schema["$defs"]["DraftValues"]["properties"]
        self.assertIn("day_schedules",values)
        self.assertIn("max_leg_travel_minutes",values)
        self.assertIn("origin_hint",values)
        self.assertNotIn("origin_poi_id",values)

    def test_new_expressions_require_original_evidence_and_reject_generated_anchor_facts(self):
        request=DraftRequest(text="TEST ONLY 每段最多30分钟，从杭州东站出发",reference_date="2026-10-22")
        cases=[({"values":{"max_leg_travel_minutes":30},"evidence":{}},"ungrounded_agent_output"),
            ({"values":{"origin_hint":"编造的酒店"},"evidence":{"origin_hint":"杭州东站"}},"ungrounded_agent_output"),
            ({"values":{"origin_hint":{"id":"made-up"}},"evidence":{"origin_hint":"杭州东站"}},"invalid_agent_output"),
            ({"values":{"day_schedules":[{"stay_minutes":True}]},"evidence":{"day_schedules":"TEST ONLY"}},"invalid_agent_output"),
            ({"values":{"days":1,"day_schedules":[{},{}]},"evidence":{"days":"TEST ONLY","day_schedules":"TEST ONLY"}},"invalid_agent_output")]
        for arguments,expected in cases:
            with self.subTest(expected=expected),self.assertRaises(TravelFailure) as error:
                validate_submission(request,arguments)
            self.assertEqual(error.exception.code,expected)

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
