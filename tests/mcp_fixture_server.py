"""Explicit TEST ONLY MCP peer, with no production import/configuration path."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--test-fixtures-only",action="store_true",required=True)
    parser.add_argument("--scenario",choices=["good","malformed","error","unknown_error","hang","slow_start","missing","exit","text_only","invalid_route","mismatched_poi","maximum_endpoints","alternatives","paced","rate_hint","rate_bool","rate_large","rate_text"],default="good")
    parser.add_argument("--record",type=Path)
    args=parser.parse_args()
    if args.record and not args.record.resolve().is_relative_to((ROOT/".tmp").resolve()):
        raise SystemExit("Test records must stay in .tmp")
    def record(event,**data):
        if args.record:
            with args.record.open("a",encoding="utf-8") as out:
                out.write(json.dumps({"event":event,"pid":os.getpid(),**data})+"\n")
    record("started")
    if args.scenario=="slow_start": time.sleep(2)
    from mcp.server.fastmcp import FastMCP
    from mcp.types import CallToolResult, TextContent
    from test_travel import FixtureProvider
    from travel.tools import TravelTools
    if args.scenario in {"good", "maximum_endpoints", "alternatives", "paced"}:
        # Exercise the production server's actual registered output schemas.
        # Only the test process replaces its provider; production has no switch.
        from travel import mcp_server
        if args.scenario == 'paced':
            from unittest.mock import Mock
            from travel.provider import AmapProvider
            from travel.provider_gate import ProviderGate
            client=Mock(enabled=True)
            def forbidden(**kwargs):
                record('unexpected_http')
                raise AssertionError('TEST ONLY: cooldown must prevent HTTP')
            client.poi_detail.side_effect=forbidden
            mcp_server.TravelTools=lambda:TravelTools(AmapProvider(client,gate=ProviderGate(args.record.with_suffix('.sqlite3'))))
        elif args.scenario == 'alternatives':
            from test_poi_comparison import AlternativeProvider
            mcp_server.TravelTools=lambda:TravelTools(AlternativeProvider())
        elif args.scenario == 'maximum_endpoints':
            from test_journey_endpoints import LargeEndpointProvider
            mcp_server.TravelTools=lambda:TravelTools(LargeEndpointProvider())
        else:
            mcp_server.TravelTools=lambda:TravelTools(FixtureProvider())
        try: mcp_server.server.run(transport="stdio")
        finally: record("stopped")
        return
    server=FastMCP("TEST ONLY travel data")
    async def call(name,arguments):
        record("call",name=name)
        if args.scenario=="exit": os._exit(3)
        if args.scenario.startswith('rate_'):
            delay={'rate_hint':3,'rate_bool':True,'rate_large':301,'rate_text':'SECRET'}[args.scenario]
            envelope={'error':{'code':'provider_rate_limited','message':'SECRET key=TEST ONLY','retryable':False,'retry_after':delay}}
            return CallToolResult(isError=True,structuredContent=envelope,content=[TextContent(type='text',text=json.dumps(envelope))])
        if args.scenario=="hang" and name=="get_route":
            try: await asyncio.sleep(30)
            finally: record("call_cancelled")
        if args.scenario in {"error","unknown_error"}:
            envelope={"error":{"code":"provider_not_configured" if args.scenario=="error" else "TEST ONLY SECRET",
                "message":"https://test.invalid/?key=TEST_ONLY_SECRET","retryable":False}}
            return CallToolResult(isError=True,structuredContent=envelope,content=[TextContent(type="text",text=json.dumps(envelope))])
        if args.scenario=="malformed": return {"data":{"token":"TEST_ONLY_SECRET"}}
        data=TravelTools(FixtureProvider()).invoke(name,arguments)
        if args.scenario=="text_only":
            return CallToolResult(content=[TextContent(type="text",text=json.dumps({"data":data}))])
        if args.scenario=="invalid_route" and name=="get_route": data["polyline"]=[]
        if args.scenario=="mismatched_poi" and name=="get_poi": data["id"]="another-test-id"
        return {"data":data}
    @server.tool()
    async def search_pois(keyword:str,city:str,limit:int=20)->dict[str, Any]:
        return await call("search_pois",{"keyword":keyword,"city":city,"limit":limit})
    @server.tool()
    async def get_poi(poi_id:str)->dict[str, Any]:
        return await call("get_poi",{"poi_id":poi_id})
    if args.scenario!="missing":
        @server.tool()
        async def get_route(origin:dict,destination:dict,mode:str="walking")->dict[str, Any]:
            return await call("get_route",{"origin":origin,"destination":destination,"mode":mode})
    try: server.run(transport="stdio")
    finally: record("stopped")


if __name__=="__main__": main()
