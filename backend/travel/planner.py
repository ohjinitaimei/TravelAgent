"""Adapt online facts to existing recommendation, ordering and scheduling code."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable
from uuid import uuid4

from core.schemas import POI, ParsedIntent
from services import poi_ranker, route_planner
from travel.provider import AmapProvider, TravelFailure
from travel.schemas import Budget, Day, GroupingOptimization, Itinerary, PlanningMetrics, PlanRequest, Poi, Stop, TimeConflictDay, TimeConstraintDiagnostics, TravelConstraintDiagnostics
from travel.tools import TravelTools
from travel.planning_budget import planning_budget, TOOL_CALL_LIMIT
from travel.endpoints import daily_endpoints, anchor_ids
from travel.travel_load import travel_load, within_travel_limits


def legacy(poi: Poi, request: PlanRequest) -> POI:
    # Numeric compatibility placeholders stay internal. Factual-only ranking
    # explicitly excludes unknown fields; no legacy POI is serialized to clients.
    return POI(id=poi.id, name=poi.name, city=request.city,
               category=poi.category or "", address=poi.address,
               latitude=poi.latitude, longitude=poi.longitude, rating=poi.rating or 0,
               visit_duration=request.stay_minutes_by_poi.get(poi.id, request.stay_minutes), provider="amap",
               factual_fields=["rating"] if poi.rating is not None else [])


def plan(request: PlanRequest, emit: Callable[[str, str], None], *, provider: AmapProvider | None = None,
         poi_ids_by_day: list[list[str]] | None = None, optimize_order: bool = True,
         parent_id: str | None = None, gateway: TravelTools | None = None) -> Itinerary:
    budget = planning_budget(request, poi_ids_by_day, optimize_order)
    provider = gateway or TravelTools(provider)
    emit("search", "正在查询高德真实 POI")
    intent = ParsedIntent(city=request.city, original_query=request.query, start_time=request.day_start,
                          end_time=request.day_end, budget=request.budget, transport_mode=request.mode)
    poi_cache = {}
    def detail(poi_id):
        if poi_id not in poi_cache:
            poi_cache[poi_id] = provider.detail(poi_id)
        return poi_cache[poi_id]
    if poi_ids_by_day is not None:
        groups = [[detail(poi_id) for poi_id in ids] for ids in poi_ids_by_day]
    else:
        pois = provider.search(request.query, request.city)
        required = request.days * request.stops_per_day
        if len(pois) < required:
            raise TravelFailure("insufficient_real_pois", f"真实有效 POI 仅 {len(pois)} 个，需求为 {required} 个；请调整关键词或站数", status=422)
        emit("ranking", "复用现有推荐函数；仅使用可核验字段")
        ranked = poi_ranker.rank_pois([legacy(poi, request) for poi in pois], intent, top_k=required, factual_only=True)
        by_id = {poi.id: poi for poi in pois}
        poi_cache.update(by_id)
        chosen = [by_id[item["poi"].id] for item in ranked]
        groups = [chosen[index:index + request.stops_per_day] for index in range(0, required, request.stops_per_day)]

    if anchor_ids(request):
        emit("anchor_lookup", "正在核对所选出发地与返回地")
    anchors = [(detail(day.origin_poi_id) if day.origin_poi_id else None,
                detail(day.destination_poi_id) if day.destination_poi_id else None) for day in daily_endpoints(request)]
    has_anchors = any(origin or destination for origin, destination in anchors)

    comparison = None
    automatic_grouping = poi_ids_by_day is None and optimize_order and request.days > 1 and request.stops_per_day > 1
    candidates = []
    candidate_search_limited = budget.candidate_search_limited
    if automatic_grouping:
        emit("grouping", "正在比较每日地点的地理分组；交通结果仍以高德为准")
        proposed = route_planner.propose_day_group_candidates([[legacy(poi, request) for poi in group] for group in groups], max_route_pairs=budget.interstop_routes)
        candidates = [[[by_id[poi.id] for poi in group] for group in partition] for partition in proposed]
        # Moving a POI to another day can require a new lodging leg. Count the
        # union of all directed facts before querying any candidate routes.
        def required_pairs(partition):
            pairs = set()
            for group, (origin, destination) in zip(partition, anchors):
                pairs.update((a.id, b.id) for a in group for b in group if a.id != b.id)
                if origin: pairs.update((origin.id, poi.id) for poi in group if origin.id != poi.id)
                if destination: pairs.update((poi.id, destination.id) for poi in group if destination.id != poi.id)
            return pairs
        reserved = required_pairs(groups)
        accepted = []
        for partition in candidates:
            combined = reserved | required_pairs(partition)
            if budget.lookup_calls + len(combined) <= TOOL_CALL_LIMIT:
                accepted.append(partition)
                reserved = combined
            else:
                candidate_search_limited = True
        candidates = accepted

    warnings = ["未验证预约、闭馆日及出行日期的营业状态；请在出发前确认。",
                "交通时间为接口查询时的估计，不保证未来出发日的实际耗时。",
                "关键词用于 POI 召回；每日时段、停留时间、交通模式和预算以表单为准。",
                "已计入所选出发地与返回地交通；未设置的一侧不包含往返，日内排序不保证全局最优。" if has_anchors else
                "未包含住宿或出发点往返交通；日内排序不保证全局最优。"]
    if request.day_endpoints is not None:
        warnings.append("每天的起终点独立核验；未自动安排前一天返回地至次日出发地的跨夜接驳。")
    warnings.append("仅比较有限地理交换候选与原分日，不保证跨日全局最优。" if automatic_grouping else
                    "保留用户指定分日，不自动跨日移动地点。" if poi_ids_by_day is not None else "按推荐顺序分日。")
    if candidate_search_limited:
        warnings.append("已为每日往返预留工具额度，分日候选查询范围受 64 次调用上限约束。")
    # Request-local reuse only. Directed A->B and B->A remain separate facts.
    segments = {}
    end_limit = route_planner._time_to_minutes(request.day_end)
    start_time = route_planner._time_to_minutes(request.day_start)
    def route(a, b):
        if a.id == b.id:
            return None  # Same adjacent POI needs no route, never a fabricated zero-minute Segment.
        key = (a.id, b.id)
        if key not in segments:
            segments[key] = provider.route(a, b, request.mode)
        return segments[key]
    def clock(minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def evaluate(day_groups, label):
        days, travel_minutes, day_minutes = [], [], []
        distance = 0.0
        feasible = True
        for index, group in enumerate(day_groups):
            origin_poi, destination_poi = anchors[index]
            emit("routing", f"{label}第 {index + 1} 天：查询真实交通矩阵")
            day_segments = {}
            pairs = ((a, b) for a in group for b in group if a.id != b.id) if optimize_order else zip(group, group[1:])
            for origin, destination in pairs:
                day_segments[(origin.id, destination.id)] = route(origin, destination)
            if origin_poi or destination_poi:
                emit("boundary_routing", "正在查询真实出发与返回交通")
            if optimize_order:
                for poi in group:
                    if origin_poi: route(origin_poi, poi)
                    if destination_poi: route(poi, destination_poi)
            internal = [legacy(poi, request) for poi in group]
            emit("optimizing", f"{label}第 {index + 1} 天：" + ("复用现有最近邻排序" if optimize_order else "保留用户指定顺序"))
            ordered = route_planner._optimize_order_by_distance(internal,
                distance_fn=lambda a, b: day_segments[(a.id, b.id)].distance_km,
                start_distance_fn=(lambda poi: 0 if poi.id == origin_poi.id else segments[(origin_poi.id, poi.id)].distance_km) if origin_poi else None) if optimize_order else internal
            lookup = {poi.id: poi for poi in group}
            incoming = route(origin_poi, lookup[ordered[0].id]) if origin_poi else None
            outgoing = route(lookup[ordered[-1].id], destination_poi) if destination_poi else None
            matrix = {key: {} for key in ("distance_km", "duration_min")}
            for (origin, destination), segment in day_segments.items():
                for key in matrix:
                    matrix[key].setdefault(origin, {})[destination] = getattr(segment, key)
            # Existing scheduler receives factual entries for every scheduled leg. Geographic
            # proposal distances never enter route, time or budget calculations.
            intent.planning_distance_matrix = matrix
            emit("scheduling", f"{label}第 {index + 1} 天：复用现有时间调度")
            scheduled = route_planner._build_route_stops(ordered, intent, start_minutes=start_time + (incoming.duration_min if incoming else 0))
            last_end = int(scheduled[-1].end_time) if scheduled else start_time
            last_end += outgoing.duration_min if outgoing else 0
            feasible = feasible and last_end <= end_limit
            day_minutes.append(last_end - start_time)
            stops, duration = [], sum(segment.duration_min for segment in (incoming, outgoing) if segment)
            distance += sum(segment.distance_km for segment in (incoming, outgoing) if segment)
            for position, stop in enumerate(scheduled):
                poi = lookup[stop.poi.id]
                cost = request.user_prices.get(poi.id)
                segment = day_segments.get((poi.id, scheduled[position + 1].poi.id)) if position + 1 < len(scheduled) else None
                if segment:
                    duration += segment.duration_min
                    distance += segment.distance_km
                stops.append(Stop(poi=poi, arrival_time=stop.arrival_time, departure_time=stop.departure_time,
                                  stay_minutes=int(stop.poi.visit_duration), user_cost=cost,
                                  cost_source="user_input" if cost is not None else None, travel_to_next=segment))
            travel_minutes.append(duration)
            days.append(Day(date=request.start_date + timedelta(days=index), stops=stops,
                origin_poi=origin_poi, destination_poi=destination_poi, origin_segment=incoming, destination_segment=outgoing,
                origin_departure_time=request.day_start if origin_poi else None,
                return_arrival_time=clock(last_end) if destination_poi else None))
        feasible = feasible and within_travel_limits(travel_load(days, request))
        return days, PlanningMetrics(distance_km=round(distance, 6), travel_minutes=sum(travel_minutes),
            busiest_day_minutes=max(day_minutes, default=0), per_day_travel_minutes=travel_minutes, feasible=feasible)

    days, baseline = evaluate(groups, "原方案：" if automatic_grouping else "")
    baseline_ids = [[stop.poi.id for stop in day.stops] for day in days]
    result = baseline
    if automatic_grouping:
        candidate_metrics = []
        applied, reason = False, "no_geographic_change"
        def score(metrics):
            return (not metrics.feasible, metrics.busiest_day_minutes, metrics.travel_minutes, metrics.distance_km)

        for index, partition in enumerate(candidates):
            alternative, metrics = evaluate(partition, f"地理候选 {index + 1}：")
            candidate_metrics.append(metrics)
            no_worse = (metrics.travel_minutes <= baseline.travel_minutes and
                        metrics.distance_km <= baseline.distance_km + 1e-6 and
                        metrics.busiest_day_minutes <= baseline.busiest_day_minutes)
            better = (metrics.travel_minutes < baseline.travel_minutes or
                      metrics.distance_km < baseline.distance_km - 1e-6 or
                      metrics.busiest_day_minutes < baseline.busiest_day_minutes)
            acceptable = metrics.feasible and (not baseline.feasible or no_worse and better)
            if acceptable and (not applied or score(metrics) < score(result)):
                applied, days, result = True, alternative, metrics
        reason = "feasible_candidate" if applied and not baseline.feasible else "improved" if applied else "baseline_preferred" if candidates else "tool_budget_limited" if candidate_search_limited else "no_geographic_change"
        comparison = GroupingOptimization(applied=applied, reason=reason, baseline=baseline,
            candidates=candidate_metrics, result=result, baseline_poi_ids_by_day=baseline_ids,
            route_queries=len(segments), candidate_route_limit=budget.interstop_routes,
            candidate_search_limited=candidate_search_limited)
    if not result.feasible:
        # Explain the original partition, never present an infeasible candidate
        # as an accepted trip. Reuse the already queried matrix; no extra calls.
        available = end_limit - start_time
        conflicts = []
        for index, group in enumerate(groups):
            stay = sum(request.stay_minutes_by_poi.get(poi.id, request.stay_minutes) for poi in group)
            total_travel = baseline.per_day_travel_minutes[index]
            incoming = days[index].origin_segment.duration_min if days[index].origin_segment else 0
            outgoing = days[index].destination_segment.duration_min if days[index].destination_segment else 0
            travel = total_travel - incoming - outgoing
            required = stay + total_travel
            if required > available:
                conflicts.append(TimeConflictDay(day_number=index + 1, stay_minutes=stay,
                    travel_minutes=travel, origin_travel_minutes=incoming, destination_travel_minutes=outgoing,
                    required_minutes=required, overrun_minutes=required - available))
        if conflicts:
            diagnostics = TimeConstraintDiagnostics(operation="adjust" if parent_id else "plan",
                source_itinerary_id=parent_id, day_start=request.day_start, day_end=request.day_end,
                available_minutes=available, days=conflicts)
            raise TravelFailure("time_constraint_exceeded", "行程超过每日结束时间；请调整每日时段、站数或停留时长", status=422, time_constraints=diagnostics)
        load = travel_load(days, request)
        diagnostics = TravelConstraintDiagnostics(**load.model_dump(), operation="adjust" if parent_id else "plan", source_itinerary_id=parent_id)
        diagnostics.days = [day for day in load.days if day.over_daily_minutes or day.violating_legs]
        raise TravelFailure("travel_constraint_exceeded", "真实路线超出所设交通时长上限；请调整地点、交通模式或明确修改上限", status=422, travel_constraints=diagnostics)
    if comparison:
        emit("grouping_validated", "真实路线核验通过，已采用更合适的分日" if comparison.applied else "真实路线核验后保留原分日")

    unknown = [f"{stop.poi.name}：实际消费/门票" for day in days for stop in day.stops if stop.user_cost is None]
    unknown.extend(f"{stop.poi.name}：完整交通费用" for day in days for stop in day.stops if stop.travel_to_next is not None)
    for index, day in enumerate(days):
        prefix = f"第 {index + 1} 天：" if request.days > 1 else ""
        if day.origin_segment: unknown.append(prefix + "出发地至首站：完整交通费用")
        if day.destination_segment: unknown.append(prefix + "末站至返回地：完整交通费用")
    unknown.append("住宿、餐饮及其他未录入费用")
    known = round(sum(stop.user_cost or 0 for day in days for stop in day.stops), 2)
    status = "exceeded" if request.budget is not None and known > request.budget else "unknown"
    if status == "exceeded":
        warnings.append("已知费用已超过预算上限；请调整行程或预算。")
    emit("validated", "真实路线和时间约束已检查，预算缺失项已标记")
    return Itinerary(id=uuid4().hex, parent_id=parent_id, title=f"{request.city} · {request.days} 日行程",
                     request=request, days=days,
                     budget=Budget(limit=request.budget, known_subtotal=known, unknown_items=unknown, status=status), warnings=warnings,
                     optimization=comparison, travel_load=travel_load(days, request),
                     algorithm="ranker_engine + bounded geographic day exchange + route_planner nearest-neighbor + route_planner scheduler" if comparison else Itinerary.model_fields['algorithm'].default)
