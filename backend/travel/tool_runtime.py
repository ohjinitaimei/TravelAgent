"""Select a backend-only transport without changing data providers or algorithms."""
from contextlib import contextmanager
import os

from services.amap_client import AmapClient
from travel.provider import TravelFailure
from travel.schemas import Error, ToolServiceStatus
from travel.tools import TravelTools


def transport():
    value=os.getenv("TRAVEL_TOOL_TRANSPORT","direct")
    if value not in {"direct","mcp"}:
        raise TravelFailure("invalid_tool_transport","工具传输配置无效，请选择 direct 或 mcp",status=503)
    return value


@contextmanager
def open_tools(emit=lambda *_:None):
    if transport()=="direct":
        yield TravelTools()
    else:
        from travel.mcp_client import open_mcp_provider
        emit("tool_connecting","正在连接受控数据工具服务")
        with open_mcp_provider() as provider:
            emit("tool_connected","工具服务握手及白名单检查通过")
            yield TravelTools(provider)


def check_service():
    from travel.mcp_client import open_mcp_provider
    mode=transport()
    try:
        # Handshake/catalog only: no provider request, model call or paid quota.
        with open_mcp_provider():
            return ToolServiceStatus(transport=mode,mcp_state="available",provider_configured=AmapClient().enabled,tools=list(TravelTools.definitions))
    except TravelFailure as error:
        return ToolServiceStatus(transport=mode,mcp_state="unavailable",provider_configured=AmapClient().enabled,
            error=Error(code=error.code,message=error.message,retryable=error.retryable))
