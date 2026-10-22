from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TimeConflictDay(Model):
    day_number: int = Field(ge=1, le=3)
    stay_minutes: int = Field(ge=0)
    travel_minutes: int = Field(ge=0)
    origin_travel_minutes: int = Field(default=0, ge=0)
    destination_travel_minutes: int = Field(default=0, ge=0)
    required_minutes: int = Field(ge=0)
    overrun_minutes: int = Field(gt=0)
    day_start: str | None = None
    day_end: str | None = None
    available_minutes: int | None = Field(default=None, gt=0, le=1439)


class TimeConstraintDiagnostics(Model):
    operation: Literal["plan", "adjust"]
    source_itinerary_id: str | None = None
    basis: Literal["original_partition"] = "original_partition"
    day_start: str
    day_end: str
    available_minutes: int = Field(gt=0, le=1439)
    days: list[TimeConflictDay] = Field(min_length=1, max_length=3)


class TravelLegViolation(Model):
    kind: Literal["origin", "interstop", "destination"]
    origin_id: str
    destination_id: str
    duration_min: int = Field(ge=0)
    overrun_minutes: int = Field(gt=0)


class TravelLoadDay(Model):
    day_number: int = Field(ge=1, le=3)
    stay_minutes: int = Field(ge=0)
    travel_minutes: int = Field(ge=0)
    longest_leg_minutes: int | None = Field(default=None, ge=0)
    travel_share_of_scheduled: float = Field(ge=0, le=1)
    travel_at_least_stay: bool
    over_daily_minutes: int = Field(default=0, ge=0)
    violating_legs: list[TravelLegViolation] = Field(default_factory=list, max_length=5)


class TravelLoad(Model):
    mode: Literal["walking", "driving"]
    max_leg_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    max_daily_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    days: list[TravelLoadDay] = Field(min_length=1, max_length=3)


class TravelConstraintDiagnostics(TravelLoad):
    operation: Literal["plan", "adjust"]
    source_itinerary_id: str | None = None
    basis: Literal["original_partition"] = "original_partition"


class Error(Model):
    code: str
    message: str
    retryable: bool = False
    retry_after: int | None = Field(default=None, strict=True, ge=1, le=300, description="建议等待的秒数；不代表服务届时一定可用，也不触发自动提交")
    time_constraints: TimeConstraintDiagnostics | None = None
    travel_constraints: TravelConstraintDiagnostics | None = None


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


class DayEndpoints(Model):
    origin_poi_id: str | None = Field(default=None, min_length=1, max_length=100)
    destination_poi_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_ids(self):
        if any(value is not None and not value.strip() for value in (self.origin_poi_id, self.destination_poi_id)):
            raise ValueError("出发地与返回地 ID 不得为空白")
        return self


class DaySchedule(Model):
    day_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    stay_minutes: int = Field(strict=True, ge=10, le=360, description="当日默认停留；逐站用户设置优先")

    @model_validator(mode="after")
    def validate_window(self):
        if self.day_end <= self.day_start:
            raise ValueError("当日结束时间必须晚于开始时间，不支持跨夜时段")
        return self


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
    compare_poi_alternatives: bool = Field(default=False, strict=True, description="新规划可比较同次真实搜索的同类备选地点；编辑不自动替换，最多三个候选且共享工具预算；评分为排序参考，不作为用户未设定的硬下限")
    user_prices: dict[str, float] = Field(default_factory=dict, description="用户提供的每站费用；不使用人均消费代替门票")
    stay_minutes_by_poi: StayOverrides = Field(default_factory=dict, description="用户指定的逐站停留时长，优先于默认时长", max_length=12)
    max_leg_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439, description="用户设置的每段交通分钟上限，含所选出发及返回，按当前交通模式核验")
    max_daily_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439, description="用户设置的每日全部交通分钟上限，含所选出发及返回")
    day_origin_poi_id: str | None = Field(default=None, min_length=1, max_length=100, description="每日共享出发 POI；每日开始表示离开该地点")
    day_destination_poi_id: str | None = Field(default=None, min_length=1, max_length=100, description="每日共享返回 POI；每日结束约束返回到达")
    day_endpoints: list[DayEndpoints] | None = Field(default=None, min_length=1, max_length=3, description="逐日独立起终点，按日期排序且长度等于 days；启用时共享起终点须为空，空侧不计往返")
    day_schedules: list[DaySchedule] | None = Field(default=None, min_length=1, max_length=3, description="逐日时段与默认停留，长度等于 days；空值沿用共用设置，逐站停留优先")

    @model_validator(mode="after")
    def validate_constraints(self):
        if not self.city.strip() or not self.query.strip():
            raise ValueError("城市与关键词不得为空")
        if self.day_end <= self.day_start:
            raise ValueError("每日结束时间必须晚于开始时间")
        if self.day_schedules is not None and len(self.day_schedules) != self.days:
            raise ValueError("逐日时段须与天数一致")
        if any(value is not None and not value.strip() for value in (self.day_origin_poi_id, self.day_destination_poi_id)):
            raise ValueError("出发地与返回地 ID 不得为空白")
        if self.day_endpoints is not None:
            if len(self.day_endpoints) != self.days or self.day_origin_poi_id or self.day_destination_poi_id:
                raise ValueError("逐日起终点须与天数一致，且不能同时设置共享起终点")
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
    max_leg_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    max_daily_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    day_origin_poi_id: str | None = Field(default=None, min_length=1, max_length=100)
    day_destination_poi_id: str | None = Field(default=None, min_length=1, max_length=100)
    day_endpoints: list[DayEndpoints] | None = Field(default=None, min_length=1, max_length=3)
    day_schedules: list[DaySchedule] | None = Field(default=None, min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_ids(self):
        ids = [item for day in self.poi_ids_by_day for item in day]
        if self.day_schedules is not None and len(self.day_schedules) != len(self.poi_ids_by_day):
            raise ValueError("逐日时段须与天数一致")
        if self.day_endpoints is not None and len(self.day_endpoints) != len(self.poi_ids_by_day):
            raise ValueError("逐日起终点须与天数一致")
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
    origin_poi: Poi | None = None
    destination_poi: Poi | None = None
    origin_segment: Segment | None = None
    destination_segment: Segment | None = None
    origin_departure_time: str | None = None
    return_arrival_time: str | None = None
    schedule: DaySchedule | None = Field(default=None, description="本次核验实际采用的用户时段与当日默认停留；旧记录为空")


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
    busiest_day_minutes: int = Field(ge=0, description="最忙一天的停留与全部已选交通总分钟数，含所选起终点往返")
    per_day_travel_minutes: list[int]
    feasible: bool


class GroupingOptimization(Model):
    strategy: Literal["bounded_geographic_exchange"] = "bounded_geographic_exchange"
    applied: bool
    reason: Literal["improved", "feasible_candidate", "baseline_preferred", "no_geographic_change", "tool_budget_limited"]
    baseline: PlanningMetrics
    candidates: list[PlanningMetrics] = Field(default_factory=list, max_length=3)
    result: PlanningMetrics
    baseline_poi_ids_by_day: list[list[str]]
    route_queries: int = Field(ge=0, le=63, description="本任务去重后的真实路线查询数，含所选起终点")
    candidate_route_limit: int | None = Field(default=None, ge=0, le=48)
    candidate_search_limited: bool = False


class RouteQualityMetrics(PlanningMetrics):
    longest_leg_minutes: int | None = Field(default=None, ge=0)


class PlanningCandidate(Model):
    kind: Literal["grouping", "replacement", "ordering"]
    poi_ids_by_day: list[list[str]]
    metrics: RouteQualityMetrics


class PlanningComparison(Model):
    strategy: Literal["bounded_real_poi_comparison"] = "bounded_real_poi_comparison"
    applied: bool
    reason: Literal["improved", "feasible_candidate", "baseline_preferred", "no_eligible_candidate", "tool_budget_limited", "no_transport_legs"]
    baseline: RouteQualityMetrics
    result: RouteQualityMetrics
    baseline_days: list[Day] = Field(min_length=1, max_length=3, description="同任务真实事实核验的原方案，不是另一已保存版本；可能不可行")
    candidates: list[PlanningCandidate] = Field(default_factory=list, max_length=3)
    result_poi_ids_by_day: list[list[str]]
    search_poi_count: int = Field(ge=1, le=20)
    proposed_candidate_count: int = Field(ge=0, le=3)
    budget_pruned_count: int = Field(ge=0, le=3)
    candidate_search_limited: bool = False
    route_queries: int = Field(ge=0, le=63)
    provider_calls: int = Field(ge=1, le=64, description="本任务网关逻辑调用数，不是上游计费账单")
    provider_call_upper_bound: int = Field(ge=1, le=64)


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
    travel_load: TravelLoad | None = None
    planning_comparison: PlanningComparison | None = None

    @classmethod
    def from_saved_json(cls, data: str) -> Itinerary:
        import json
        value = json.loads(data)
        # New plans get a creation time. Reading an old record must not manufacture one.
        if isinstance(value, dict) and "created_at" not in value:
            value["created_at"] = ""
        return cls.model_validate(value)


class ItineraryQuery(Model):
    limit: int = Field(default=50, ge=1, le=100)
    query: str = Field(default="", max_length=120)
    kind: Literal["all", "original", "adjusted"] = "all"
    order: Literal["newest", "oldest", "departure"] = "newest"
    parent_id: str | None = Field(default=None, min_length=1, max_length=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class ItineraryList(Model):
    items: list[Itinerary]
    total: int | None = Field(default=None, ge=0, description="当前账号、查询与快照内的匹配版本总数")
    page_cursor: str | None = Field(default=None, description="当前页快照游标；不是授权凭证")
    next_cursor: str | None = None
    direct_adjustment_counts: dict[str, int] = Field(default_factory=dict, description="当前页各版本在同账号快照内的直接调整数，不受搜索条件影响")


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


class DraftDaySchedule(Model):
    """User expressions may be incomplete; no planner defaults are inferred here."""
    day_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    stay_minutes: int | None = Field(default=None, strict=True, ge=10, le=360)

    @model_validator(mode="after")
    def valid_window(self):
        if self.day_start and self.day_end and self.day_start >= self.day_end:
            raise ValueError("逐日结束时段须晚于开始时段，不支持跨夜")
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
    day_schedules: list[DraftDaySchedule] | None = Field(default=None, min_length=1, max_length=3,
        description="按第1天至末日排列；未表达的子字段保留null，不继承表单默认；补充时完整替换数组")
    max_leg_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    max_daily_travel_minutes: int | None = Field(default=None, strict=True, ge=1, le=1439)
    origin_hint: str | None = Field(default=None, strict=True, min_length=1, max_length=100,
        description="用户出发地原文，仅作待核对的搜索提示，不是已选POI或ID")
    destination_hint: str | None = Field(default=None, strict=True, min_length=1, max_length=100,
        description="用户返回地原文，仅作待核对的搜索提示，不是已选POI或ID")

    @model_validator(mode="after")
    def valid_fields(self):
        if any(value is not None and not value.strip() for value in (self.city, self.query, self.origin_hint, self.destination_hint)):
            raise ValueError("城市、关键词与地点提示不得为空白")
        if self.day_start and self.day_end and self.day_start >= self.day_end:
            raise ValueError("结束时段须晚于开始时段")
        if self.days is not None and self.day_schedules is not None and len(self.day_schedules) != self.days:
            raise ValueError("逐日时段数量须与旅行天数一致；请同时核对天数与逐日设置")
        return self


class DraftSubmission(Model):
    values: DraftValues
    evidence: dict[str, str] = Field(max_length=15)
    unhandled_requirements: list[str] = Field(default_factory=list, max_length=12)


DraftField = Literal["city", "query", "start_date", "days", "stops_per_day", "day_start", "day_end", "stay_minutes", "mode", "budget",
                     "day_schedules", "max_leg_travel_minutes", "max_daily_travel_minutes", "origin_hint", "destination_hint"]


class DraftClarificationRequest(Model):
    expected_revision: int = Field(ge=1, strict=True)
    values: DraftValues = Field(default_factory=DraftValues)
    confirm_fields: list[DraftField] = Field(default_factory=list, max_length=15)

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
    values: dict[DraftField, str | int | float | list[DraftDaySchedule] | None]
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
