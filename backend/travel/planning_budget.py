"""Conservative per-plan tool budget shared by admission, planner and QA.

No provider facts or traffic estimates are produced here. Request-local caching
can reduce actual calls; it must never be needed to satisfy the default cap.
"""
from dataclasses import dataclass

from travel.provider import TravelFailure

TOOL_CALL_LIMIT = 64
GROUP_ROUTE_LIMIT = 48


@dataclass(frozen=True)
class PlanningBudget:
    lookup_calls: int
    boundary_routes: int
    interstop_routes: int
    candidate_search_limited: bool

    @property
    def route_calls(self):
        return self.boundary_routes + self.interstop_routes

    @property
    def total_calls(self):
        return self.lookup_calls + self.route_calls


def planning_budget(request, poi_ids_by_day=None, optimize_order=True):
    sizes = [len(day) for day in poi_ids_by_day] if poi_ids_by_day is not None else [request.stops_per_day] * request.days
    count = sum(sizes)
    anchors = {value for value in (request.day_origin_poi_id, request.day_destination_poi_id) if value}
    selected = {item for day in poi_ids_by_day for item in day} if poi_ids_by_day is not None else set()
    lookups = len(selected | anchors) if poi_ids_by_day is not None else 1 + len(anchors)
    boundary = (count if optimize_order else len(sizes)) * sum(bool(value) for value in (request.day_origin_poi_id, request.day_destination_poi_id))
    baseline = sum(size * (size - 1) if optimize_order else size - 1 for size in sizes)
    automatic = poi_ids_by_day is None and optimize_order and request.days > 1 and request.stops_per_day > 1
    old_limit = min(GROUP_ROUTE_LIMIT, count * (count - 1))
    interstop = min(old_limit, TOOL_CALL_LIMIT - lookups - boundary) if automatic else baseline
    if interstop < baseline or lookups + boundary + interstop > TOOL_CALL_LIMIT:
        raise TravelFailure('planning_budget_exceeded', '本次重新排序超出 64 次工具调用上限；请保留原顺序、减少站点或清除一侧起终点后重试', status=422)
    return PlanningBudget(lookups, boundary, interstop, automatic and interstop < old_limit)
