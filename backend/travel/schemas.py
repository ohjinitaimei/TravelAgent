from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Error(Model):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(Model):
    error: Error


class AuthUser(Model):
    id: str
    username: str


class LoginRequest(Model):
    username: str = Field(min_length=3,max_length=40,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,39}$")
    password: SecretStr = Field(min_length=1,max_length=128)
    transport: Literal["cookie","bearer"] = "cookie"


class AuthStatus(Model):
    mode: Literal["local","session"]
    authenticated: bool
    user: AuthUser | None = None
    csrf_token: str | None = None
    expires_at: str | None = None
    setup_required: bool = False


class LoginResponse(AuthStatus):
    access_token: str | None = None
    token_type: Literal["Bearer"] = "Bearer"


class Source(Model):
    provider: Literal["amap", "user_input"]
    retrieved_at: str = Field(default_factory=now)
    coordinate_system: Literal["GCJ-02"] = "GCJ-02"


class Poi(Model):
    id: str
    name: str
    city: str | None = None
    address: str | None = None
    category: str | None = None
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    rating: float | None = None
    average_spend: float | None = None
    opening_hours: str | None = None
    source: Source
    missing_fields: list[str] = Field(default_factory=list)


class PoiList(Model):
    items: list[Poi]


class Point(Model):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class RouteQuery(Model):
    origin: Point
    destination: Point
    mode: Literal["walking", "driving"] = "walking"


class PoiSearch(Model):
    keyword: str = Field(min_length=1, max_length=240)
    city: str = Field(min_length=1, max_length=60)
    limit: int = Field(default=20, ge=1, le=20)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.keyword.strip() or not self.city.strip():
            raise ValueError("城市与关键词不得为空")
        return self


class PoiDetail(Model):
    poi_id: str = Field(min_length=1, max_length=100)


StayOverrides = dict[str, Annotated[int, Field(strict=True, ge=10, le=360)]]


class Segment(Model):
    origin_id: str
    destination_id: str
    mode: Literal["walking", "driving"]
    distance_km: float = Field(ge=0)
    duration_min: int = Field(ge=0)
    tolls: float | None = None
    total_cost: float | None = None
    polyline: list[Point]
    source: Source


class PlanRequest(Model):
    city: str = Field(min_length=1, max_length=60)
    query: str = Field(min_length=1, max_length=240, description="POI 搜索关键词与偏好；硬约束以结构化字段为准")
    start_date: date
    days: int = Field(default=2, ge=1, le=3)
    stops_per_day: int = Field(default=3, ge=1, le=4)
    day_start: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    stay_minutes: int = Field(default=60, ge=10, le=360, description="用户指定停留时长，不代表 POI 官方建议")
    mode: Literal["walking", "driving"] = "walking"
    budget: float | None = Field(default=None, ge=0)
    user_prices: dict[str, float] = Field(default_factory=dict, description="用户提供的每站费用；不使用人均消费代替门票")
    stay_minutes_by_poi: StayOverrides = Field(default_factory=dict, description="用户指定的逐站停留时长，优先于默认时长", max_length=12)

    @model_validator(mode="after")
    def validate_constraints(self):
        if not self.city.strip() or not self.query.strip():
            raise ValueError("城市与关键词不得为空")
        if self.day_end <= self.day_start:
            raise ValueError("每日结束时间必须晚于开始时间")
        if len(self.user_prices) > 12 or any(value < 0 for value in self.user_prices.values()):
            raise ValueError("用户费用必须非负且最多 12 项")
        return self


class EditRequest(Model):
    poi_ids_by_day: list[list[str]] = Field(min_length=1, max_length=3)
    stay_minutes: int | None = Field(default=None, ge=10, le=360)
    user_prices: dict[str, float] | None = None
    optimize_order: bool = False
    stay_minutes_by_poi: StayOverrides | None = Field(default=None, max_length=12)
    start_date: date | None = None
    day_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    mode: Literal["walking", "driving"] | None = None
    budget: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ids(self):
        ids = [item for day in self.poi_ids_by_day for item in day]
        if any(not day or len(day) > 4 for day in self.poi_ids_by_day):
            raise ValueError("每天必须包含 1 至 4 个 POI")
        if any(not item or len(item) > 100 for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("POI ID 不得为空或重复")
        if self.user_prices is not None:
            if len(self.user_prices) > 12 or any(value < 0 for value in self.user_prices.values()):
                raise ValueError("用户费用必须非负且最多 12 项")
            if set(self.user_prices) - set(ids):
                raise ValueError("费用只能关联行程中的 POI")
        if self.stay_minutes_by_poi is not None and set(self.stay_minutes_by_poi) - set(ids):
            raise ValueError("停留时长只能关联行程中的 POI")
        if any(getattr(self, field) is None for field in self.model_fields_set & {"start_date", "day_start", "day_end", "mode"}):
            raise ValueError("日期、每日时段与交通方式不能为 null")
        return self


class Stop(Model):
    poi: Poi
    arrival_time: str
    departure_time: str
    stay_minutes: int
    stay_source: Literal["user_input"] = "user_input"
    user_cost: float | None = None
    cost_source: Literal["user_input"] | None = None
    travel_to_next: Segment | None = None


class Day(Model):
    date: date
    stops: list[Stop]


class Budget(Model):
    limit: float | None = None
    known_subtotal: float
    total: float | None = None
    currency: Literal["CNY"] = "CNY"
    unknown_items: list[str]
    status: Literal["unknown", "exceeded"]


class PlanningMetrics(Model):
    distance_km: float = Field(ge=0)
    travel_minutes: int = Field(ge=0)
    busiest_day_minutes: int = Field(ge=0, description="最忙一天的游览与站间交通总分钟数，不包含住宿往返")
    per_day_travel_minutes: list[int]
    feasible: bool


class GroupingOptimization(Model):
    strategy: Literal["bounded_geographic_exchange"] = "bounded_geographic_exchange"
    applied: bool
    reason: Literal["improved", "feasible_candidate", "baseline_preferred", "no_geographic_change"]
    baseline: PlanningMetrics
    candidates: list[PlanningMetrics] = Field(default_factory=list, max_length=3)
    result: PlanningMetrics
    baseline_poi_ids_by_day: list[list[str]]
    route_queries: int = Field(ge=0, le=48)


class Itinerary(Model):
    id: str
    parent_id: str | None = None
    created_at: str = Field(default_factory=now)
    title: str
    request: PlanRequest
    days: list[Day]
    budget: Budget
    warnings: list[str]
    algorithm: str = "ranker_engine + route_planner nearest-neighbor + route_planner scheduler"
    optimization: GroupingOptimization | None = None


class ItineraryList(Model):
    items: list[Itinerary]


class Event(Model):
    id: int
    timestamp: str = Field(default_factory=now)
    stage: str
    message: str


class EventList(Model):
    items: list[Event]


class Task(Model):
    id: str
    kind: Literal["plan", "draft"] = "plan"
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    itinerary_id: str | None = None
    draft_id: str | None = None
    error: Error | None = None
    retry_of: str | None = None
    retry_available: bool = False


class Capabilities(Model):
    provider: Literal["amap"] = "amap"
    configured: bool
    transport_modes: list[str] = ["walking", "driving"]
    agent: str = "deterministic_existing_algorithms"
    mcp_connected: bool = False
    mcp_available: bool = False
    tool_transport: Literal["direct", "mcp"] = "direct"
    helloagents_available: bool = False
    draft_enabled: bool = False
    llm_configured: bool = False
    limitations: list[str]


class ToolServiceStatus(Model):
    transport: Literal["direct", "mcp"]
    mcp_state: Literal["available", "unavailable"]
    checked_at: str = Field(default_factory=now)
    provider_configured: bool
    tools: list[str] = Field(default_factory=list)
    error: Error | None = None


class DraftRequest(Model):
    text: str = Field(min_length=1, max_length=2000)
    reference_date: date

    @model_validator(mode="after")
    def nonempty(self):
        if not self.text.strip():
            raise ValueError("旅行需求不得为空")
        return self


class DraftValues(Model):
    city: str | None = Field(default=None, min_length=1, max_length=60)
    query: str | None = Field(default=None, min_length=1, max_length=240)
    start_date: date | None = None
    days: int | None = Field(default=None, strict=True, ge=1, le=3)
    stops_per_day: int | None = Field(default=None, strict=True, ge=1, le=4)
    day_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    stay_minutes: int | None = Field(default=None, strict=True, ge=10, le=360)
    mode: Literal["walking", "driving"] | None = None
    budget: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_fields(self):
        if any(value is not None and not value.strip() for value in (self.city, self.query)):
            raise ValueError("城市与关键词不得为空白")
        if self.day_start and self.day_end and self.day_start >= self.day_end:
            raise ValueError("结束时段须晚于开始时段")
        return self


class DraftSubmission(Model):
    values: DraftValues
    evidence: dict[str, str] = Field(max_length=10)
    unhandled_requirements: list[str] = Field(default_factory=list, max_length=12)


DraftField = Literal["city", "query", "start_date", "days", "stops_per_day", "day_start", "day_end", "stay_minutes", "mode", "budget"]


class DraftClarificationRequest(Model):
    expected_revision: int = Field(ge=1, strict=True)
    values: DraftValues = Field(default_factory=DraftValues)
    confirm_fields: list[DraftField] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def meaningful_change(self):
        if not self.values.model_fields_set and not self.confirm_fields:
            raise ValueError("请选择要确认或补充的字段")
        if len(set(self.confirm_fields)) != len(self.confirm_fields):
            raise ValueError("确认字段不得重复")
        return self


class DraftClarification(Model):
    revision: int
    timestamp: str = Field(default_factory=now)
    values: dict[DraftField, str | int | float | None]
    confirmed_fields: list[DraftField]


class Draft(Model):
    id: str
    created_at: str = Field(default_factory=now)
    input: DraftRequest
    proposal: DraftSubmission
    source: Literal["helloagents"] = "helloagents"
    questions: list[str]
    warnings: list[str]
    coordinator_action: Literal["continue", "ask_clarification"]
    revision: int = 1
    updated_at: str | None = None
    confirmed_fields: list[DraftField] = Field(default_factory=list)
    field_sources: dict[DraftField, Literal["model_extracted", "user_input"]] = Field(default_factory=dict)
    clarifications: list[DraftClarification] = Field(default_factory=list)
