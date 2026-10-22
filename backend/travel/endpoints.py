"""Resolve user-selected daily boundaries; no inferred lodging or transfers."""
from travel.schemas import DayEndpoints


def daily_endpoints(request):
    custom = getattr(request, 'day_endpoints', None)
    if custom is not None:
        return custom
    return [DayEndpoints(origin_poi_id=request.day_origin_poi_id,
                         destination_poi_id=request.day_destination_poi_id) for _ in range(request.days)]


def anchor_ids(request):
    return {value for day in daily_endpoints(request) for value in (day.origin_poi_id, day.destination_poi_id) if value}
