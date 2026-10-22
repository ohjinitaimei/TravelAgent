"""Real stdio client, planner and task lifecycle; all successes are TEST ONLY."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from mcp import StdioServerParameters
from fastapi.testclient import TestClient
from agent.travel_tool_bridge import online_registry
from travel.mcp_client import McpLimits, bundled_parameters, open_mcp_provider
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import PlanRequest
from travel.tools import TravelTools
from test_travel import PAYLOAD


def process_alive(pid):
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87: return False
            raise ctypes.WinError(ctypes.get_last_error())
        try: return kernel.WaitForSingleObject(handle,0)==258
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid,0)
    except ProcessLookupError: return False
    stat=Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(") ",1)[1].startswith("Z"))


def parameters(scenario="good",record=None):
    args=[str(ROOT/"tests/mcp_fixture_server.py"),"--test-fixtures-only","--scenario",scenario]
    if record: args += ["--record",str(record)]
    return StdioServerParameters(command=sys.executable,args=args,cwd=str(ROOT),env={"PYTHONIOENCODING":"utf-8"})


def fixture_mcp_worker(payload,output):
    from travel.worker import run
    record=Path(os.environ["TRAVEL_MCP_TEST_RECORD"])
    with patch("travel.mcp_client.bundled_parameters",lambda:parameters("hang",record)):
        run(payload,output)


class McpClientTests(unittest.TestCase):
    def test_daily_windows_and_stop_priority_share_real_stdio_without_more_calls(self):
        from test_daily_schedules import SCHEDULES
        request=PlanRequest.model_validate({**PAYLOAD,'days':2,'stops_per_day':1,'day_schedules':SCHEDULES,
            'stay_minutes_by_poi':{'fixture-b':20},'day_origin_poi_id':'home'})
        with open_mcp_provider(parameters=parameters()) as provider:
            trip=plan(request,lambda *_:None,provider=provider)
            self.assertEqual(provider.client.calls,4)
            self.assertEqual([day.origin_departure_time for day in trip.days],['08:00','14:00'])
            self.assertEqual([day.stops[0].arrival_time for day in trip.days],['08:37','14:37'])
            self.assertEqual([day.stops[0].stay_minutes for day in trip.days],[30,20])

    def test_daily_boundaries_share_real_stdio_and_keep_default_call_budget(self):
        daily=[{'origin_poi_id':'home-1','destination_poi_id':'hotel-1'}, {'origin_poi_id':'home-2','destination_poi_id':None}]
        request=PlanRequest.model_validate({**PAYLOAD,'days':2,'stops_per_day':1,'day_endpoints':daily})
        with open_mcp_provider(parameters=parameters()) as provider:
            trip=plan(request,lambda *_:None,provider=provider)
            self.assertEqual(provider.client.calls,7)
            self.assertEqual([day.origin_poi.id for day in trip.days],['home-1','home-2'])
            self.assertEqual([day.stops[0].arrival_time for day in trip.days],['09:37','09:37'])
            self.assertEqual(trip.days[0].return_arrival_time,'11:14')
            self.assertIsNone(trip.days[1].destination_poi)
        with open_mcp_provider(parameters=parameters(),limits=McpLimits(max_calls=6)) as provider:
            with self.assertRaises(TravelFailure) as caught:plan(request,lambda *_:None,provider=provider)
            self.assertEqual(caught.exception.code,'tool_budget_exhausted')

    def test_shared_cooldown_crosses_real_stdio_and_hint_is_sanitized(self):
        from travel.provider_gate import ProviderGate
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            record=Path(folder)/'paced.jsonl'
            ProviderGate(record.with_suffix('.sqlite3'),cooldown=10).rejected()
            with open_mcp_provider(parameters=parameters('paced',record)) as provider:
                with self.assertRaises(TravelFailure) as caught:provider.detail('fixture-a')
                self.assertEqual(caught.exception.code,'provider_rate_limited')
                self.assertTrue(1<=caught.exception.retry_after<=10)
                self.assertEqual(provider.client.calls,1)
            rows=[json.loads(line) for line in record.read_text().splitlines()]
            self.assertFalse(any(row['event']=='unexpected_http' for row in rows))
        for scenario,expected in [('rate_hint',3),('rate_bool',None),('rate_large',None),('rate_text',None)]:
            with self.subTest(scenario=scenario),open_mcp_provider(parameters=parameters(scenario)) as provider:
                with self.assertRaises(TravelFailure) as caught:provider.detail('fixture-a')
                self.assertEqual(caught.exception.retry_after,expected)
                self.assertEqual(caught.exception.status,429);self.assertTrue(caught.exception.retryable)
                self.assertNotIn('SECRET',str(caught.exception));self.assertEqual(provider.client.calls,1)

    def test_endpoints_reuse_the_same_mcp_provider_and_preserve_budget_failures(self):
        request=PlanRequest.model_validate({**PAYLOAD,'day_origin_poi_id':'TEST ONLY home','day_destination_poi_id':'TEST ONLY hotel'})
        with open_mcp_provider(parameters=parameters()) as provider:
            trip=plan(request,lambda *_:None,provider=provider)
            self.assertEqual(trip.days[0].stops[0].arrival_time,'09:37')
            self.assertEqual(trip.days[0].return_arrival_time,'12:51')
            self.assertEqual(trip.days[0].origin_segment.origin_id,'TEST ONLY home')
            self.assertEqual(trip.days[0].destination_segment.destination_id,'TEST ONLY hotel')
        with open_mcp_provider(parameters=parameters(),limits=McpLimits(max_calls=3)) as provider:
            with self.assertRaises(TravelFailure) as caught:plan(request,lambda *_:None,provider=provider)
            self.assertEqual(caught.exception.code,'tool_budget_exhausted')

    def test_maximum_multiday_shared_endpoints_fit_real_stdio_default_budget(self):
        request=PlanRequest.model_validate({**PAYLOAD,'days':3,'stops_per_day':4,'stay_minutes':10,
                                           'day_origin_poi_id':'home','day_destination_poi_id':'hotel'})
        with open_mcp_provider(parameters=parameters('maximum_endpoints')) as provider:
            trip=plan(request,lambda *_:None,provider=provider)
            self.assertEqual(provider.client.calls,63)
            self.assertEqual(trip.optimization.route_queries,60)
            self.assertEqual([day.origin_departure_time for day in trip.days],['09:00']*3)
            groups=[[stop.poi.id for stop in day.stops] for day in trip.days]
        with open_mcp_provider(parameters=parameters('maximum_endpoints')) as provider:
            child=plan(request,lambda *_:None,provider=provider,poi_ids_by_day=groups,optimize_order=False)
            self.assertEqual(provider.client.calls,29)
            self.assertEqual(child.days[2].destination_poi.id,'hotel')

    def test_stdio_travel_limits_use_factual_legs_without_extra_tool_calls(self):
        for limit in (36,37):
            with self.subTest(limit=limit),open_mcp_provider(parameters=parameters()) as provider:
                request=PlanRequest.model_validate({**PAYLOAD,'max_leg_travel_minutes':limit})
                if limit==36:
                    with self.assertRaises(TravelFailure) as caught:plan(request,lambda *_:None,provider=provider)
                    self.assertEqual(caught.exception.code,'travel_constraint_exceeded')
                    self.assertEqual(caught.exception.travel_constraints.days[0].violating_legs[0].duration_min,37)
                else:
                    trip=plan(request,lambda *_:None,provider=provider)
                    self.assertEqual(trip.travel_load.days[0].longest_leg_minutes,37)
                self.assertEqual(provider.client.calls,3)

    def test_planner_and_existing_registry_use_the_same_client(self):
        events=[]
        with open_mcp_provider(parameters=parameters()) as provider:
            trip=plan(PlanRequest.model_validate(PAYLOAD),lambda stage,_:events.append(stage),provider=provider)
            self.assertEqual(len(trip.days[0].stops),2)
            self.assertEqual(trip.days[0].stops[0].travel_to_next.duration_min,37)
            self.assertEqual(trip.days[0].stops[0].travel_to_next.origin_id,trip.days[0].stops[0].poi.id)
            self.assertTrue(all(stop.poi.name.startswith("TEST ONLY") for stop in trip.days[0].stops))
            self.assertEqual(trip.budget.status,"unknown")
            registry=online_registry(TravelTools(provider),max_calls=1)
            result=registry.run("get_poi",poi_id="fixture-a")
            self.assertEqual(result.status,"ok")
            self.assertFalse(result.fallback_used)
            self.assertEqual(registry.run("get_poi",poi_id="fixture-a").error,"tool_budget_exhausted")
        self.assertIn("scheduling",events)

    def test_allowlist_validation_and_call_budget(self):
        with open_mcp_provider(parameters=parameters(),limits=McpLimits(max_calls=1)) as provider:
            for name,args,code in [("delete_file",{},"unknown_tool"),("get_poi",{},"invalid_tool_arguments")]:
                with self.assertRaises(TravelFailure) as error: provider.invoke(name,args)
                self.assertEqual(error.exception.code,code)
            self.assertEqual(provider.detail("fixture-a").id,"fixture-a")
            with self.assertRaises(TravelFailure) as error: provider.detail("fixture-a")
            self.assertEqual(error.exception.code,"tool_budget_exhausted")

    def test_results_and_remote_errors_are_sanitized(self):
        for scenario,code in [("malformed","invalid_mcp_response"),("error","provider_not_configured"),("unknown_error","mcp_tool_failed")]:
            with self.subTest(scenario=scenario),open_mcp_provider(parameters=parameters(scenario)) as provider:
                with self.assertRaises(TravelFailure) as error: provider.detail("fixture-a")
                self.assertEqual(error.exception.code,code)
                self.assertNotIn("SECRET",str(error.exception))
                self.assertNotIn("key=",str(error.exception))

    def test_handshake_timeout_and_missing_tools_fail_closed(self):
        for scenario,limits,code in [("missing",McpLimits(),"mcp_contract_mismatch"),("slow_start",McpLimits(connect_seconds=.05),"mcp_connect_timeout")]:
            with self.subTest(scenario=scenario),self.assertRaises(TravelFailure) as error:
                with open_mcp_provider(parameters=parameters(scenario),limits=limits): pass
            self.assertEqual(error.exception.code,code)

    def test_call_timeout_invalidates_session_without_retry(self):
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder:
            record=Path(folder)/"peer.jsonl"
            with open_mcp_provider(parameters=parameters("hang",record),limits=McpLimits(call_seconds=.15)) as provider:
                origin,destination=provider.search("TEST ONLY","TEST ONLY")
                with self.assertRaises(TravelFailure) as error: provider.route(origin,destination,"walking")
                self.assertEqual(error.exception.code,"mcp_call_timeout")
                with self.assertRaises(TravelFailure) as error: provider.detail("fixture-a")
                self.assertEqual(error.exception.code,"mcp_session_unavailable")
            records=[json.loads(line) for line in record.read_text().splitlines()]
            self.assertEqual([r["name"] for r in records if r["event"]=="call"],["search_pois","get_route"])
            self.assertFalse(process_alive(records[0]["pid"]),"Timed-out MCP peer remains alive")

    def test_unexpected_peer_exit_is_bounded(self):
        started=time.monotonic()
        with open_mcp_provider(parameters=parameters("exit"),limits=McpLimits(call_seconds=.3)) as provider:
            with self.assertRaises(TravelFailure) as error: provider.detail("fixture-a")
            self.assertIn(error.exception.code,{"mcp_unavailable","mcp_call_timeout"})
        self.assertLess(time.monotonic()-started,8)

    def test_total_budget_expiry_does_not_reconnect(self):
        with open_mcp_provider(parameters=parameters(),limits=McpLimits(total_seconds=1)) as provider:
            self.assertEqual(provider.detail("fixture-a").id,"fixture-a")
            time.sleep(1.05)
            with self.assertRaises(TravelFailure) as error: provider.detail("fixture-a")
            self.assertEqual(error.exception.code,"tool_budget_exhausted")

    def test_invalid_facts_and_text_only_results_do_not_become_fallback_data(self):
        for scenario in ("text_only","mismatched_poi","invalid_route"):
            with self.subTest(scenario=scenario),open_mcp_provider(parameters=parameters(scenario)) as provider:
                with self.assertRaises(TravelFailure) as error:
                    if scenario=="invalid_route":
                        origin,destination=provider.search("TEST ONLY","TEST ONLY")
                        provider.route(origin,destination,"walking")
                    else: provider.detail("fixture-a")
                self.assertEqual(error.exception.code,"invalid_mcp_response")

    def test_production_command_environment_and_configuration_are_restricted(self):
        from travel.tool_runtime import transport
        with patch.dict(os.environ,{"TRAVEL_LLM_API_KEY":"TEST ONLY SECRET","GITHUB_TOKEN":"TEST ONLY SECRET","AMAP_WEB_KEY":""}):
            params=bundled_parameters()
            self.assertEqual(params.command,sys.executable)
            self.assertEqual(params.args,["-m","travel.mcp_server"])
            self.assertNotIn("TRAVEL_LLM_API_KEY",params.env)
            self.assertNotIn("GITHUB_TOKEN",params.env)
        for name,value in [("TRAVEL_MCP_CALL_TIMEOUT","nan"),("TRAVEL_MCP_MAX_CALLS","1000")]:
            with patch.dict(os.environ,{name:value}),self.assertRaises(TravelFailure): McpLimits.from_env()
        with patch.dict(os.environ,{"TRAVEL_TOOL_TRANSPORT":"arbitrary-command"}),self.assertRaises(TravelFailure): transport()

    def test_real_bundled_server_and_rest_preserve_missing_authorization(self):
        from main import app
        env={"AMAP_KEY":"","AMAP_WEB_KEY":"","TRAVEL_TOOL_TRANSPORT":"mcp"}
        with tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder,patch.dict(os.environ,{**env,"TRAVEL_DB_PATH":str(Path(folder)/"api.sqlite3")}),TestClient(app) as client:
            status=client.post("/api/v1/travel/tool-service/check")
            self.assertEqual(status.status_code,200,status.text)
            self.assertEqual(status.json()["mcp_state"],"available")
            self.assertFalse(status.json()["provider_configured"])
            self.assertEqual(client.get("/api/v1/travel/capabilities").json()["tool_transport"],"mcp")
            response=client.get("/api/v1/travel/pois",params={"keyword":"公园","city":"北京"})
            self.assertEqual(response.status_code,503,response.text)
            self.assertEqual(response.json()["error"]["code"],"provider_not_configured")
            task=client.post("/api/v1/travel/tasks",json=PAYLOAD).json()
            final=self.wait_task(client,task["id"])
            self.assertEqual(final["status"],"failed",final)
            self.assertEqual(final["error"]["code"],"provider_not_configured")
            self.assertIsNone(final["itinerary_id"])
            stages=[item["stage"] for item in client.get(f"/api/v1/travel/tasks/{task['id']}/events").json()["items"]]
            self.assertIn("tool_connected",stages)

    def wait_task(self,client,identifier):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            task=client.get(f"/api/v1/travel/tasks/{identifier}").json()
            if task["status"] not in {"queued","running"}: return task
            time.sleep(.05)
        self.fail("Task did not terminate")

    def test_cancel_and_task_timeout_close_the_mcp_peer(self):
        from main import app
        for action in ("cancel","timeout"):
            with self.subTest(action=action),tempfile.TemporaryDirectory(dir=ROOT/".tmp") as folder:
                folder=Path(folder);record=folder/"peer.jsonl"
                env={"TRAVEL_DB_PATH":str(folder/"api.sqlite3"),"TRAVEL_TOOL_TRANSPORT":"mcp","TRAVEL_MCP_TEST_RECORD":str(record)}
                with patch.dict(os.environ,env),patch("travel.tasks.run",fixture_mcp_worker),TestClient(app) as client:
                    if action=="timeout": app.state.travel.timeout=8
                    task=client.post("/api/v1/travel/tasks",json=PAYLOAD).json()
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        rows=[json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
                        if any(row.get("name")=="get_route" for row in rows): break
                        time.sleep(.05)
                    else: self.fail("Worker never reached MCP route call")
                    if action=="cancel": client.post(f"/api/v1/travel/tasks/{task['id']}/cancel")
                    final=self.wait_task(client,task["id"])
                    self.assertEqual(final["status"],"cancelled" if action=="cancel" else "timed_out")
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    rows=[json.loads(line) for line in record.read_text().splitlines()]
                    if not process_alive(rows[0]["pid"]): break
                    time.sleep(.1)
                else: self.fail("MCP child did not close after its worker terminated")


if __name__=="__main__":
    (ROOT/".tmp").mkdir(exist_ok=True)
    unittest.main()
