"""Resolve user schedule preferences; traffic and routing stay in the planner."""
from travel.schemas import DaySchedule


def daily_schedules(request):
    if request.day_schedules is not None:
        return request.day_schedules
    return [DaySchedule(day_start=request.day_start, day_end=request.day_end, stay_minutes=request.stay_minutes)
            for _ in range(request.days)]


def stay_minutes(request, poi_id, day_index):
    return request.stay_minutes_by_poi.get(poi_id, daily_schedules(request)[day_index].stay_minutes)
