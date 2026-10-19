"""Adapt the existing registry to the shared real-data gateway; no new loop."""
from time import monotonic

from agent.tool_layer import ToolRegistry, ToolResult
from travel.provider import TravelFailure
from travel.tools import TravelTools


def online_registry(gateway=None, *, max_calls=4, deadline_seconds=30, emit=lambda *_: None):
    gateway = gateway or TravelTools()
    registry = ToolRegistry()
    remaining, deadline = max_calls, monotonic() + deadline_seconds

    def invoke(name, arguments):
        nonlocal remaining
        if remaining <= 0 or monotonic() >= deadline:
            return ToolResult(tool=name, status="failed", error="tool_budget_exhausted", fallback_used=False)
        remaining -= 1
        emit("tool_call", f"正在调用真实数据工具 {name}")
        try:
            result = gateway.invoke(name, arguments)
            emit("tool_result", f"真实数据工具 {name} 已返回")
            return ToolResult(tool=name, payload=result, evidence=["authorized_provider_or_user_input"],
                              noise_risk="low", used_by=["travel"], fallback_used=False)
        except TravelFailure as error:
            emit("tool_failed", f"工具 {name} 失败：{error.code}")
            return ToolResult(tool=name, status="failed", error=error.code, fallback_used=False,
                              payload={"error":{"code":error.code,"message":error.message,"retryable":error.retryable}})
        except Exception:
            return ToolResult(tool=name, status="failed", error="tool_failed", fallback_used=False)

    def handler(name):
        return lambda **arguments: invoke(name, arguments)
    for name in gateway.definitions:
        registry.register(name, handler(name))
    return registry
