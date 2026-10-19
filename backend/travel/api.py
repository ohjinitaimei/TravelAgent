from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Header, Query, Request
from typing import Annotated
from fastapi.responses import StreamingResponse

from services.amap_client import AmapClient
from travel.provider import TravelFailure
from travel.schemas import (Capabilities, Draft, DraftClarificationRequest, DraftRequest, EditRequest, ErrorResponse, EventList, Itinerary,
                            ItineraryList, PlanRequest, Poi, PoiList, RouteQuery, Segment, Task, ToolServiceStatus)
from travel.tasks import TERMINAL
from travel.tool_runtime import open_tools, transport, check_service
from travel.auth import require_user, owner_id

router = APIRouter(prefix="/api/v1/travel", tags=["travel"], dependencies=[Depends(require_user)], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
})
SubmissionKey = Annotated[str | None, Header(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


def manager(request: Request):
    return request.app.state.travel


def task_or_fail(request: Request, task_id: str):
    task = manager(request).store.task(task_id,owner_id=owner_id(request))
    if not task:
        raise TravelFailure("task_not_found", "任务不存在", status=404)
    return task


def trip_or_fail(request: Request, itinerary_id: str):
    trip = manager(request).store.itinerary(itinerary_id,owner_id=owner_id(request))
    if not trip:
        raise TravelFailure("itinerary_not_found", "行程不存在", status=404)
    return trip


@router.get("/capabilities", response_model=Capabilities)
def capabilities():
    import importlib.util
    from agent.travel_intake import status
    return Capabilities(configured=AmapClient().enabled, tool_transport=transport(), mcp_available=importlib.util.find_spec("mcp") is not None, **status(), limitations=[
        "单 API 实例；账号模式按用户隔离，本地模式共享本地空间", "无真实评论、酒店报价、门票库存或预约能力",
        "预算仅汇总用户录入费用，未知费用不等于免费", "自然语言仅整理需求，须核对表单；无跨日全局优化",
    ])


@router.post("/tool-service/check", response_model=ToolServiceStatus)
def check_tool_service():
    return check_service()


@router.post("/tasks", response_model=Task, status_code=202)
async def create_task(body: PlanRequest, request: Request, idempotency_key: SubmissionKey = None):
    return manager(request).create({"request": body.model_dump(mode="json")}, idempotency_key,owner_id=owner_id(request))


@router.post("/drafts", response_model=Task, status_code=202)
async def create_draft(body: DraftRequest, request: Request, idempotency_key: SubmissionKey = None):
    return manager(request).create({"kind":"draft","request":body.model_dump(mode="json")}, idempotency_key,owner_id=owner_id(request))


@router.get("/submissions/{submission_key}", response_model=Task)
def get_submission(submission_key: str, request: Request):
    task = manager(request).store.submission(submission_key,owner_id=owner_id(request))
    if not task:
        raise TravelFailure("submission_not_found", "尚未找到该提交，可使用相同标识恢复提交", status=404)
    return task


@router.post("/tasks/{task_id}/retry", response_model=Task, status_code=202)
async def retry_task(task_id: str, request: Request, idempotency_key: SubmissionKey = None):
    return manager(request).retry(task_id, idempotency_key,owner_id=owner_id(request))


@router.get("/drafts/{draft_id}", response_model=Draft)
def get_draft(draft_id: str, request: Request):
    draft = manager(request).store.draft(draft_id,owner_id=owner_id(request))
    if not draft:
        raise TravelFailure("draft_not_found", "需求草案不存在", status=404)
    return draft


@router.patch("/drafts/{draft_id}", response_model=Draft)
def clarify_draft(draft_id: str, body: DraftClarificationRequest, request: Request):
    from travel.drafts import clarify
    draft = clarify(get_draft(draft_id, request), body)
    manager(request).store.update_draft(draft, body.expected_revision,owner_id=owner_id(request))
    return draft


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, request: Request):
    return task_or_fail(request, task_id)


@router.post("/tasks/{task_id}/cancel", response_model=Task)
async def cancel_task(task_id: str, request: Request):
    task_or_fail(request, task_id)
    return manager(request).cancel(task_id)


@router.get("/tasks/{task_id}/events", response_model=EventList)
async def events(task_id: str, request: Request, after: int = Query(default=0, ge=0)):
    task_or_fail(request, task_id)
    return EventList(items=manager(request).store.events(task_id, after))


@router.get("/tasks/{task_id}/events/stream", response_class=StreamingResponse)
async def stream(task_id: str, request: Request, after: int = Query(default=0, ge=0),
                 last_event_id: str | None = Header(default=None)):
    task_or_fail(request, task_id)
    if last_event_id is not None:
        try:
            after = max(after, int(last_event_id))
        except ValueError:
            raise TravelFailure("invalid_event_cursor", "无效事件游标", status=422) from None

    async def generate():
        cursor, heartbeat = after, 0
        while not await request.is_disconnected():
            if request.app.state.auth.identify(request) is None:
                yield 'event: auth_required\ndata: {"error":{"code":"authentication_required"}}\n\n'
                return
            for event in manager(request).store.events(task_id, cursor):
                cursor = event.id
                yield f"id: {cursor}\nevent: progress\ndata: {event.model_dump_json()}\n\n"
            task = task_or_fail(request, task_id)
            if task.status in TERMINAL:
                # Event and state mutations occur on the event loop; no await
                # separates the snapshot and terminal transition.
                yield f"event: terminal\ndata: {task.model_dump_json()}\n\n"
                return
            heartbeat += 1
            if heartbeat % 30 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.get("/itineraries", response_model=ItineraryList)
def list_itineraries(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    return ItineraryList(items=manager(request).store.itineraries(limit,owner_id=owner_id(request)))


@router.get("/itineraries/{itinerary_id}", response_model=Itinerary)
def get_itinerary(itinerary_id: str, request: Request):
    return trip_or_fail(request, itinerary_id)


@router.post("/itineraries/{itinerary_id}/adjust", response_model=Task, status_code=202)
async def adjust(itinerary_id: str, body: EditRequest, request: Request, idempotency_key: SubmissionKey = None):
    trip = trip_or_fail(request, itinerary_id)
    if len(body.poi_ids_by_day) != trip.request.days:
        raise TravelFailure("invalid_day_count", "调整行程必须保留原有天数", status=422)
    values = trip.request.model_dump(mode="json")
    for field in body.model_fields_set - {"poi_ids_by_day", "optimize_order"}:
        if getattr(body, field) is not None or field == "budget":
            values[field] = getattr(body, field)
    ids = {item for day in body.poi_ids_by_day for item in day}
    for field in ("user_prices", "stay_minutes_by_poi"):
        values[field] = {key: value for key, value in values[field].items() if key in ids}
    from pydantic import ValidationError
    try:
        validated = PlanRequest.model_validate(values)
    except ValidationError:
        raise TravelFailure("invalid_constraints", "每日结束时间须晚于开始时间，其他约束须在允许范围内", status=422) from None
    return manager(request).create({"request": validated.model_dump(mode="json"),
        "poi_ids_by_day": body.poi_ids_by_day, "optimize_order": body.optimize_order, "parent_id": trip.id}, idempotency_key,owner_id=owner_id(request))


@router.get("/pois", response_model=PoiList)
def search_pois(keyword: str = Query(min_length=1, max_length=240), city: str = Query(min_length=1, max_length=60),
                limit: int = Query(default=20, ge=1, le=20)):
    with open_tools() as tools:
        return PoiList(items=tools.search(keyword, city, limit))


@router.get("/pois/{poi_id}", response_model=Poi)
def poi_detail(poi_id: str):
    with open_tools() as tools:
        return tools.detail(poi_id)


@router.post("/routes", response_model=Segment)
def route(body: RouteQuery):
    with open_tools() as tools:
        return tools.route_query(body)
