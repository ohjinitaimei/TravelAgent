"""Spawn-safe isolated worker. Provider keys are never sent to frontends."""
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import Error, PlanRequest


def run(payload: dict, output):
    def emit(stage, message):
        output.put({"kind": "event", "stage": stage, "message": message})
    try:
        if payload.get("kind") == "draft":
            from agent.travel_intake import create_draft
            from travel.schemas import DraftRequest
            result = create_draft(DraftRequest.model_validate(payload["request"]), emit)
        else:
            from travel.tool_runtime import open_tools
            with open_tools(emit) as gateway:
                result = plan(PlanRequest.model_validate(payload["request"]), emit, gateway=gateway,
                              poi_ids_by_day=payload.get("poi_ids_by_day"),
                              optimize_order=payload.get("optimize_order", True), parent_id=payload.get("parent_id"))
        output.put({"kind": "result", "data": result.model_dump(mode="json")})
    except TravelFailure as error:
        output.put({"kind": "error", "data": Error(code=error.code, message=error.message,
            retryable=error.retryable, retry_after=error.retry_after, time_constraints=error.time_constraints, travel_constraints=error.travel_constraints).model_dump(mode="json")})
    except Exception:
        output.put({"kind": "error", "data": {"code": "planning_failed", "message": "规划执行失败，请检查服务端日志与输入", "retryable": False}})
