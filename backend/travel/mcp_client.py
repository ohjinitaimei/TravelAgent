"""Bounded MCP client for the bundled local server; no model loop or fallback.

The asynchronous stdio session lives in one portal task. Synchronous existing
algorithms call it through the portal without running on the API event loop.
"""
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timedelta
import asyncio
import math
import os
from pathlib import Path
import sys
from time import monotonic

from pydantic import ValidationError

from travel.provider import TravelFailure
from travel.schemas import Poi, PoiList, Segment
from travel.tools import TravelTools

BACKEND=Path(__file__).resolve().parents[1]
AMAP_ENV=("AMAP_KEY","AMAP_WEB_KEY","AMAP_WEB_BASE_URL","AMAP_WEB_TIMEOUT_SECONDS")
ERRORS={
    "provider_not_configured":("未配置高德 Web 服务 Key；无法查询真实数据",False,503),
    "provider_timeout":("高德接口超时",True,504),
    "provider_unavailable":("高德接口调用失败",True,502),
    "provider_rejected":("高德拒绝请求，请检查授权、权限和配额",False,502),
    "invalid_provider_response":("高德响应不符合契约",False,502),
    "poi_not_found":("POI 不存在或缺少有效坐标",False,404),
    "route_unavailable":("高德未返回可用路线",False,502),
    "route_incomplete":("真实路线缺少距离或时长",False,502),
    "route_geometry_missing":("真实路线缺少路网折线",False,502),
    "invalid_tool_arguments":("旅行工具参数不符合契约",False,422),
}


@dataclass(frozen=True)
class McpLimits:
    connect_seconds: float = 8
    call_seconds: float = 12
    total_seconds: float = 150
    max_calls: int = 64

    def __post_init__(self):
        for value,maximum in ((self.connect_seconds,30),(self.call_seconds,60),(self.total_seconds,180)):
            if not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError("Invalid MCP time limit")
        if isinstance(self.max_calls,bool) or not isinstance(self.max_calls,int) or not 1 <= self.max_calls <= 128:
            raise ValueError("Invalid MCP call limit")

    @classmethod
    def from_env(cls):
        try:
            return cls(connect_seconds=float(os.getenv("TRAVEL_MCP_CONNECT_TIMEOUT","8")),
                       call_seconds=float(os.getenv("TRAVEL_MCP_CALL_TIMEOUT","12")),
                       total_seconds=float(os.getenv("TRAVEL_MCP_TOTAL_TIMEOUT","150")),
                       max_calls=int(os.getenv("TRAVEL_MCP_MAX_CALLS","64")))
        except (ValueError,TypeError):
            raise TravelFailure("invalid_mcp_config","MCP 调用限额配置无效",status=503) from None


def bundled_parameters():
    # No command, file path or remote address is accepted from a request or LLM.
    from mcp import StdioServerParameters
    environment={name:os.environ[name] for name in AMAP_ENV if name in os.environ}
    environment.update(PYTHONIOENCODING="utf-8",PYTHONUTF8="1")
    return StdioServerParameters(command=sys.executable,args=["-m","travel.mcp_server"],cwd=str(BACKEND),env=environment)


class McpConnection:
    def __init__(self,session,limits):
        self.session,self.limits=session,limits
        self.deadline=monotonic()+limits.total_seconds
        self.calls=0
        self.broken=False

    async def invoke(self,name,arguments):
        if name not in TravelTools.definitions:
            raise TravelFailure("unknown_tool","未授权的旅行工具",status=422)
        try:
            query=TravelTools.definitions[name][0].model_validate(arguments)
        except ValidationError:
            raise TravelFailure("invalid_tool_arguments","旅行工具参数不符合契约",status=422) from None
        if self.broken:
            raise TravelFailure("mcp_session_unavailable","工具会话已中断，请重新提交任务",True,503)
        remaining=self.deadline-monotonic()
        if self.calls>=self.limits.max_calls or remaining<=0:
            raise TravelFailure("tool_budget_exhausted","工具调用次数或总时限已达到上限，请减少站数",status=429)
        self.calls+=1
        try:
            async with asyncio.timeout(min(self.limits.call_seconds,remaining)):
                result=await self.session.call_tool(name,query.model_dump(mode="json"),read_timeout_seconds=timedelta(seconds=min(self.limits.call_seconds,remaining)))
        except TimeoutError:
            self.broken=True
            raise TravelFailure("mcp_call_timeout","工具调用超时，请重试或减少站数",True,504) from None
        except Exception as error:
            self.broken=True
            # The pinned SDK may report its read deadline as JSON-RPC 408
            # just before the surrounding asyncio deadline fires.
            if getattr(getattr(error,"error",None),"code",None)==408:
                raise TravelFailure("mcp_call_timeout","工具调用超时，请重试或减少站数",True,504) from None
            raise TravelFailure("mcp_unavailable","工具连接已中断，请检查后端服务",True,503) from None
        envelope=result.structuredContent
        if not isinstance(envelope,dict) or len(result.model_dump_json())>1_000_000:
            raise TravelFailure("invalid_mcp_response","工具未返回符合契约的结构化结果")
        if result.isError:
            error=envelope.get("error")
            code=error.get("code") if isinstance(error,dict) else None
            if isinstance(code,str) and code in ERRORS:
                message,retryable,status=ERRORS[code]
                raise TravelFailure(code,message,retryable,status)
            raise TravelFailure("mcp_tool_failed","工具调用失败，请检查服务配置")
        if set(envelope)!={"data"}:
            raise TravelFailure("invalid_mcp_response","工具结果缺少业务数据")
        try:
            model={"search_pois":PoiList,"get_poi":Poi,"get_route":Segment}[name]
            data=model.model_validate(envelope["data"])
            if name=="get_poi" and data.id!=query.poi_id:
                raise ValueError("Mismatched POI")
            if name=="search_pois" and (len(data.items)>query.limit or len({p.id for p in data.items})!=len(data.items)):
                raise ValueError("Invalid search cardinality")
            if name=="get_route" and (data.mode!=query.mode or not data.polyline):
                raise ValueError("Invalid route")
            return data.model_dump(mode="json")
        except (ValidationError,ValueError,TypeError):
            raise TravelFailure("invalid_mcp_response","工具业务数据不符合契约；未生成替代结果") from None


@asynccontextmanager
async def connection(parameters,limits):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    # Server stderr can contain provider diagnostics. Never forward it to users.
    with open(os.devnull,"w") as errlog:
        async with stdio_client(parameters,errlog=errlog) as (reader,writer), ClientSession(reader,writer) as session:
            try:
                async with asyncio.timeout(limits.connect_seconds):
                    await session.initialize()
                    names=set()
                    cursor=None
                    for _ in range(3):
                        listing=await session.list_tools() if cursor is None else await session.list_tools(cursor=cursor)
                        for tool in listing.tools:
                            if tool.name in names:
                                raise TravelFailure("mcp_contract_mismatch","工具目录包含重复名称",status=503)
                            names.add(tool.name)
                            if tool.name in TravelTools.definitions:
                                expected=TravelTools.definitions[tool.name][0].model_json_schema().get("required",[])
                                schema=tool.inputSchema
                                if schema.get("type")!="object" or not set(expected)<=set(schema.get("properties",{})):
                                    raise TravelFailure("mcp_contract_mismatch","工具输入契约不匹配",status=503)
                        cursor=listing.nextCursor
                        if not cursor: break
                    if cursor or not set(TravelTools.definitions)<=names or len(names)>128:
                        raise TravelFailure("mcp_contract_mismatch","工具目录缺少约定工具或超出范围",status=503)
            except TimeoutError:
                raise TravelFailure("mcp_connect_timeout","工具服务握手超时",True,504) from None
            yield McpConnection(session,limits)


def _failure(error):
    if isinstance(error,TravelFailure): return error
    for child in getattr(error,"exceptions",[]):
        found=_failure(child)
        if found: return found
    return None


class McpProvider:
    def __init__(self,portal,client):
        self.portal,self.client=portal,client

    def invoke(self,name,arguments):
        return self.portal.call(self.client.invoke,name,arguments)

    def search(self,keyword,city,limit=20):
        return PoiList.model_validate(self.invoke("search_pois",{"keyword":keyword,"city":city,"limit":limit})).items

    def detail(self,poi_id):
        return Poi.model_validate(self.invoke("get_poi",{"poi_id":poi_id}))

    def route(self,origin,destination,mode):
        result=Segment.model_validate(self.invoke("get_route",{"origin":{"longitude":origin.longitude,"latitude":origin.latitude},
            "destination":{"longitude":destination.longitude,"latitude":destination.latitude},"mode":mode}))
        # The wire query uses coordinates; preserve the planner's endpoint IDs.
        return result.model_copy(update={"origin_id":origin.id,"destination_id":destination.id})


@contextmanager
def open_mcp_provider(*,limits=None,parameters=None):
    limits=limits or McpLimits.from_env()
    try:
        from anyio.from_thread import start_blocking_portal
        parameters=parameters or bundled_parameters()
        with start_blocking_portal() as portal, portal.wrap_async_context_manager(connection(parameters,limits)) as client:
            yield McpProvider(portal,client)
    except ImportError:
        raise TravelFailure("mcp_dependency_unavailable","请安装锁定的 MCP 可选依赖",status=503) from None
    except Exception as error:
        failure=_failure(error)
        if failure: raise failure from None
        raise TravelFailure("mcp_unavailable","工具服务连接失败，请检查后端配置",True,503) from None
