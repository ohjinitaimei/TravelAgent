"""Summarize saved, factual legs and check explicit user limits; no routing."""
from travel.schemas import TravelLoad, TravelLoadDay, TravelLegViolation


def travel_load(days, request):
    measured = []
    for index, day in enumerate(days):
        legs = [('origin', day.origin_segment),
                *[('interstop', stop.travel_to_next) for stop in day.stops],
                ('destination', day.destination_segment)]
        legs = [(kind, leg) for kind, leg in legs if leg is not None]
        stay = sum(stop.stay_minutes for stop in day.stops)
        travel = sum(leg.duration_min for _, leg in legs)
        maximum = request.max_leg_travel_minutes
        daily = request.max_daily_travel_minutes
        violations = [TravelLegViolation(kind=kind, origin_id=leg.origin_id, destination_id=leg.destination_id,
            duration_min=leg.duration_min, overrun_minutes=leg.duration_min - maximum)
            for kind, leg in legs if maximum is not None and leg.duration_min > maximum]
        measured.append(TravelLoadDay(day_number=index + 1, stay_minutes=stay, travel_minutes=travel,
            longest_leg_minutes=max((leg.duration_min for _, leg in legs), default=None),
            travel_share_of_scheduled=round(travel / (stay + travel), 4) if stay + travel else 0,
            travel_at_least_stay=travel >= stay,
            over_daily_minutes=max(0, travel - daily) if daily is not None else 0, violating_legs=violations))
    return TravelLoad(mode=request.mode, max_leg_travel_minutes=request.max_leg_travel_minutes,
                      max_daily_travel_minutes=request.max_daily_travel_minutes, days=measured)


def within_travel_limits(report):
    return all(not day.over_daily_minutes and not day.violating_legs for day in report.days)
