"""Adapt online facts to existing recommendation, ordering and scheduling code."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable
from uuid import uuid4

from core.schemas import POI, ParsedIntent
from services import poi_ranker, route_planner
from travel.provider import AmapProvider, TravelFailure
from travel.schemas import Budget, Day, GroupingOptimization, Itinerary, PlanningMetrics, PlanRequest, Poi, Stop
from travel.tools import TravelTools


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
    provider = gateway or TravelTools(provider)
    emit("search", "正在查询高德真实 POI")
    intent = ParsedIntent(city=request.city, original_query=request.query, start_time=request.day_start,
                          end_time=request.day_end, budget=request.budget, transport_mode=request.mode)
    if poi_ids_by_day is not None:
        groups = [[provider.detail(poi_id) for poi_id in ids] for ids in poi_ids_by_day]
    else:
        pois = provider.search(request.query, request.city)
        required = request.days * request.stops_per_day
        if len(pois) < required:
            raise TravelFailure("insufficient_real_pois", f"真实有效 POI 仅 {len(pois)} 个，需求为 {required} 个；请调整关键词或站数", status=422)
        emit("ranking", "复用现有推荐函数；仅使用可核验字段")
        ranked = poi_ranker.rank_pois([legacy(poi, request) for poi in pois], intent, top_k=required, factual_only=True)
        by_id = {poi.id: poi for poi in pois}
        chosen = [by_id[item["poi"].id] for item in ranked]
        groups = [chosen[index:index + request.stops_per_day] for index in range(0, required, request.stops_per_day)]

    comparison = None
    automatic_grouping = poi_ids_by_day is None and optimize_order and request.days > 1 and request.stops_per_day > 1
    candidates = []
    if automatic_grouping:
        emit("grouping", "正在比较每日地点的地理分组；交通结果仍以高德为准")
        proposed = route_planner.propose_day_group_candidates([[legacy(poi, request) for poi in group] for group in groups])
        candidates = [[[by_id[poi.id] for poi in group] for group in partition] for partition in proposed]

    warnings = ["未验证预约、闭馆日及出行日期的营业状态；请在出发前确认。",
                "交通时间为接口查询时的估计，不保证未来出发日的实际耗时。",
                "关键词用于 POI 召回；每日时段、停留时间、交通模式和预算以表单为准。",
                "未包含住宿或出发点往返交通；日内排序不保证全局最优。"]
    warnings.append("仅比较有限地理交换候选与原分日，不保证跨日全局最优。" if automatic_grouping else
                    "保留用户指定分日，不自动跨日移动地点。" if poi_ids_by_day is not None else "按推荐顺序分日。")
    # Request-local reuse only. Directed A->B and B->A remain separate facts.
    segments = {}
    end_limit = route_planner._time_to_minutes(request.day_end)
    start_time = route_planner._time_to_minutes(request.day_start)

    def evaluate(day_groups, label):
        days, travel_minutes, day_minutes = [], [], []
        distance = 0.0
        feasible = True
        for index, group in enumerate(day_groups):
            emit("routing", f"{label}第 {index + 1} 天：查询真实交通矩阵")
            day_segments = {}
            for origin in group:
                for destination in group:
                    if origin.id != destination.id:
                        key = (origin.id, destination.id)
                        if key not in segments:
                            segments[key] = provider.route(origin, destination, request.mode)
                        day_segments[key] = segments[key]
            internal = [legacy(poi, request) for poi in group]
            emit("optimizing", f"{label}第 {index + 1} 天：复用现有最近邻排序")
            ordered = route_planner._optimize_order_by_distance(internal, distance_fn=lambda a, b: day_segments[(a.id, b.id)].distance_km) if optimize_order else internal
            matrix = {key: {} for key in ("distance_km", "duration_min")}
            for (origin, destination), segment in day_segments.items():
                for key in matrix:
                    matrix[key].setdefault(origin, {})[destination] = getattr(segment, key)
            # Existing scheduler receives a complete factual matrix. Geographic
            # proposal distances never enter route, time or budget calculations.
            intent.planning_distance_matrix = matrix
            emit("scheduling", f"{label}第 {index + 1} 天：复用现有时间调度")
            scheduled = route_planner._build_route_stops(ordered, intent)
            last_end = int(scheduled[-1].end_time) if scheduled else start_time
            feasible = feasible and last_end <= end_limit
            day_minutes.append(last_end - start_time)
            lookup = {poi.id: poi for poi in group}
            stops, duration = [], 0
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
            days.append(Day(date=request.start_date + timedelta(days=index), stops=stops))
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
        reason = "feasible_candidate" if applied and not baseline.feasible else "improved" if applied else "baseline_preferred" if candidates else "no_geographic_change"
        comparison = GroupingOptimization(applied=applied, reason=reason, baseline=baseline,
            candidates=candidate_metrics, result=result, baseline_poi_ids_by_day=baseline_ids,
            route_queries=len(segments))
    if not result.feasible:
        raise TravelFailure("time_constraint_exceeded", "行程超过每日结束时间；请减少站数或停留时长", status=422)
    if comparison:
        emit("grouping_validated", "真实路线核验通过，已采用更合适的分日" if comparison.applied else "真实路线核验后保留原分日")

    unknown = [f"{stop.poi.name}：实际消费/门票" for day in days for stop in day.stops if stop.user_cost is None]
    unknown.extend(f"{stop.poi.name}：完整交通费用" for day in days for stop in day.stops if stop.travel_to_next is not None)
    unknown.append("住宿、餐饮及其他未录入费用")
    known = round(sum(stop.user_cost or 0 for day in days for stop in day.stops), 2)
    status = "exceeded" if request.budget is not None and known > request.budget else "unknown"
    if status == "exceeded":
        warnings.append("已知费用已超过预算上限；请调整行程或预算。")
    emit("validated", "真实路线和时间约束已检查，预算缺失项已标记")
    return Itinerary(id=uuid4().hex, parent_id=parent_id, title=f"{request.city} · {request.days} 日行程",
                     request=request, days=days,
                     budget=Budget(limit=request.budget, known_subtotal=known, unknown_items=unknown, status=status), warnings=warnings,
                     optimization=comparison,
                     algorithm="ranker_engine + bounded geographic day exchange + route_planner nearest-neighbor + route_planner scheduler" if comparison else Itinerary.model_fields['algorithm'].default)
