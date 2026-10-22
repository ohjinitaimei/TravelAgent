"""Opt-in, bounded real Amap quality checks through an isolated production API.

No fixture injection, model calls, production database access or automatic retries.
Fixed profiles; six plans and 138 provider calls at most.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def require(condition, label):
    if not condition:
        raise ValueError(label)


def request_budget(request):
    # Budget-only callers need counts and optional IDs, not a business request.
    from types import SimpleNamespace
    from travel.planning_budget import planning_budget
    return planning_budget(SimpleNamespace(days=request['days'], stops_per_day=request['stops_per_day'],
        day_origin_poi_id=request.get('day_origin_poi_id'), day_destination_poi_id=request.get('day_destination_poi_id'),
        day_endpoints=[SimpleNamespace(**{'origin_poi_id':day.get('origin_poi_id'),'destination_poi_id':day.get('destination_poi_id')}) for day in request['day_endpoints']] if request.get('day_endpoints') is not None else None))


def route_call_bound(request):
    return request_budget(request).route_calls


def provider_call_bound(request):
    return request_budget(request).total_calls


def scenarios(profile, travel_date):
    from travel.schemas import PlanRequest
    definitions = {
        'smoke': [('nanjing-parks', '南京', '公园', 2, 2, 'walking'),
                  ('suzhou-parks', '苏州', '公园', 2, 2, 'driving')],
        'expanded': [('nanjing-museums-3', '南京', '博物馆', 1, 3, 'walking'),
                     ('suzhou-coffee-4', '苏州', '咖啡', 1, 4, 'driving'),
                     ('suzhou-parks-12', '苏州', '公园', 3, 4, 'driving')],
        'diverse': [('hangzhou-parks-6', '杭州', '公园', 2, 3, 'walking'),
                    ('beijing-museums-3', '北京', '博物馆', 1, 3, 'driving'),
                    ('chengdu-coffee-4', '成都', '咖啡', 1, 4, 'walking')],
    }
    cases = []
    for identifier, city, keyword, days, stops, mode in definitions[profile]:
        request = PlanRequest(city=city, query=keyword, start_date=travel_date, days=days,
            stops_per_day=stops, stay_minutes=30, day_start='09:00', day_end='22:00', mode=mode).model_dump(mode='json')
        cases.append({'scenario': identifier, 'request': request, 'maximum_provider_calls': provider_call_bound(request)})
    return cases


def minute(value):
    require(isinstance(value, str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value), 'invalid_clock')
    return int(value[:2]) * 60 + int(value[3:])


def quality_observations(trip, days):
    """Describe validated saved facts; never infer satisfaction or new constraints."""
    from travel.schedules import daily_schedules
    schedules=daily_schedules(trip.request)
    observations, attention = [], []
    for index, day in enumerate(trip.days):
        measured = days[index]
        available = minute(schedules[index].day_end)-minute(schedules[index].day_start)
        elapsed = measured['stay_minutes'] + measured['travel_minutes']
        legs = []
        for position, stop in enumerate(day.stops):
            segment = stop.travel_to_next
            if segment is not None:
                legs.append({'origin_id': segment.origin_id, 'origin_name': stop.poi.name,
                    'destination_id': segment.destination_id, 'destination_name': day.stops[position + 1].poi.name,
                    'mode': segment.mode, 'duration_min': segment.duration_min, 'distance_km': segment.distance_km,
                    'source': segment.source.model_dump(mode='json')})
        for kind, segment, a, b in [('origin', day.origin_segment, day.origin_poi, day.stops[0].poi),
                                     ('destination', day.destination_segment, day.stops[-1].poi, day.destination_poi)]:
            if segment:
                legs.append({'kind': kind, 'origin_id': segment.origin_id, 'origin_name': a.name,
                    'destination_id': segment.destination_id, 'destination_name': b.name,
                    'mode': segment.mode, 'duration_min': segment.duration_min, 'distance_km': segment.distance_km,
                    'source': segment.source.model_dump(mode='json')})
        observations.append({'day_number': index + 1, 'date': str(day.date),
            'available_minutes': available, 'stay_minutes': measured['stay_minutes'],
            'travel_minutes': measured['travel_minutes'], 'scheduled_minutes': elapsed,
            'remaining_minutes': available - elapsed,
            'travel_share_of_scheduled': round(measured['travel_minutes'] / elapsed, 4),
            'longest_leg_minutes': max((leg['duration_min'] for leg in legs), default=None), 'legs': legs})
        # A transparent review cue, not a universal preference or rejection gate.
        if measured['travel_minutes'] >= measured['stay_minutes']:
            attention.append({'code': 'travel_at_least_stay', 'day_number': index + 1})
    loads = [day['scheduled_minutes'] for day in observations]
    from travel.endpoints import anchor_ids
    anchored = bool(anchor_ids(trip.request))
    return {'scope': 'saved_routes_including_selected_boundaries' if anchored else 'saved_interstop_facts_only', 'origin_return_included': anchored,
        'future_opening_verified': False, 'subjective_satisfaction': 'not_assessed',
        'day_load_spread_minutes': max(loads) - min(loads), 'days': observations, 'attention': attention}


def summarize(raw, expected):
    """Reject invalid provenance/schedules before recording a passing sample."""
    from travel.schemas import Itinerary, PlanRequest
    trip = Itinerary.model_validate(raw)
    request = PlanRequest.model_validate(expected)
    require(trip.request == request, 'request_mismatch')
    require(len(trip.days) == request.days, 'day_count')
    ids, days, missing, evidence = [], [], Counter(), []
    def boundary(poi, segment, identifier, adjacent, original_poi, original_segment, incoming):
        if identifier is None:
            require(poi is None and segment is None, 'unexpected_boundary')
            return 0, 0.0
        require(poi is not None and poi.id == identifier and poi.source.provider == 'amap', 'boundary_poi_provenance')
        require(bool(original_poi['source'].get('retrieved_at')), 'boundary_timestamp_missing')
        require(datetime.fromisoformat(poi.source.retrieved_at).tzinfo is not None, 'boundary_timestamp')
        for field in ('city', 'address', 'category', 'rating', 'average_spend', 'opening_hours'):
            require((getattr(poi, field) is None) == (field in poi.missing_fields), 'boundary_missing_field_marker')
        if identifier == adjacent.id:
            require(segment is None, 'invented_same_poi_route')
            return 0, 0.0
        require(segment is not None and segment.source.provider == 'amap', 'boundary_route_provenance')
        require(bool(original_segment['source'].get('retrieved_at')), 'boundary_route_timestamp_missing')
        require(datetime.fromisoformat(segment.source.retrieved_at).tzinfo is not None, 'boundary_route_timestamp')
        a, b = (identifier, adjacent.id) if incoming else (adjacent.id, identifier)
        require(segment.origin_id == a and segment.destination_id == b, 'boundary_route_link')
        require(segment.mode == request.mode and bool(segment.polyline), 'boundary_route_mode_geometry')
        require(segment.total_cost is None, 'invented_boundary_cost')
        return segment.duration_min, segment.distance_km
    from travel.endpoints import daily_endpoints
    endpoints = daily_endpoints(request)
    from travel.schedules import daily_schedules, stay_minutes
    schedules = daily_schedules(request)
    for index, day in enumerate(trip.days):
        selected = endpoints[index]
        schedule = schedules[index]
        if request.day_schedules is not None or day.schedule is not None:
            require(day.schedule == schedule, 'day_schedule_mismatch')
        require(day.date == request.start_date + timedelta(days=index), 'day_date')
        require(len(day.stops) == request.stops_per_day, 'stop_count')
        original_day = raw['days'][index]
        incoming, incoming_distance = boundary(day.origin_poi, day.origin_segment, selected.origin_poi_id, day.stops[0].poi,
            original_day.get('origin_poi'), original_day.get('origin_segment'), True)
        outgoing, outgoing_distance = boundary(day.destination_poi, day.destination_segment, selected.destination_poi_id, day.stops[-1].poi,
            original_day.get('destination_poi'), original_day.get('destination_segment'), False)
        require(day.origin_departure_time == (schedule.day_start if selected.origin_poi_id else None), 'origin_departure')
        arrival = minute(schedule.day_start) + incoming
        distance, travel = incoming_distance + outgoing_distance, incoming + outgoing
        for position, stop in enumerate(day.stops):
            ids.append(stop.poi.id)
            require(stop.poi.source.provider == 'amap', 'poi_provenance')
            original = raw['days'][index]['stops'][position]
            # Source defaults must not manufacture a retrieval timestamp for the report.
            require(bool(original['poi']['source'].get('retrieved_at')), 'poi_timestamp_missing')
            require(datetime.fromisoformat(stop.poi.source.retrieved_at).tzinfo is not None, 'poi_timestamp')
            for field in ('city', 'address', 'category', 'rating', 'average_spend', 'opening_hours'):
                absent = getattr(stop.poi, field) is None
                require(absent == (field in stop.poi.missing_fields), 'missing_field_marker')
                if absent:
                    missing[field] += 1
            require(stop.stay_minutes == stay_minutes(request,stop.poi.id,index), 'stay_duration')
            require(stop.stay_source == 'user_input', 'stay_provenance')
            require(minute(stop.arrival_time) == arrival, 'arrival_schedule')
            arrival += stop.stay_minutes
            require(minute(stop.departure_time) == arrival, 'departure_schedule')
            require(arrival <= minute(schedule.day_end), 'day_end_exceeded')
            require(stop.user_cost is None and stop.cost_source is None, 'invented_station_cost')
            evidence.append({'id': stop.poi.id, 'name': stop.poi.name, 'city': stop.poi.city,
                'category': stop.poi.category, 'name_contains_keyword': request.query in stop.poi.name,
                'category_contains_keyword': request.query in (stop.poi.category or '')})
            segment = stop.travel_to_next
            if position == len(day.stops) - 1:
                require(segment is None, 'unexpected_last_route')
            else:
                require(segment is not None, 'missing_route')
                require(segment.source.provider == 'amap', 'route_provenance')
                require(bool(original['travel_to_next']['source'].get('retrieved_at')), 'route_timestamp_missing')
                require(datetime.fromisoformat(segment.source.retrieved_at).tzinfo is not None, 'route_timestamp')
                require(segment.origin_id == stop.poi.id and segment.destination_id == day.stops[position + 1].poi.id, 'route_link')
                require(segment.mode == request.mode and bool(segment.polyline), 'route_mode_geometry')
                require(segment.total_cost is None, 'invented_transport_cost')
                travel += segment.duration_min
                distance += segment.distance_km
                arrival += segment.duration_min
        if request.max_daily_travel_minutes is not None:
            require(travel <= request.max_daily_travel_minutes, 'daily_travel_limit')
        factual_legs = [day.origin_segment, *[stop.travel_to_next for stop in day.stops], day.destination_segment]
        if request.max_leg_travel_minutes is not None:
            require(all(leg.duration_min <= request.max_leg_travel_minutes for leg in factual_legs if leg), 'leg_travel_limit')
        require(arrival + outgoing <= minute(schedule.day_end), 'return_end_exceeded')
        require((minute(day.return_arrival_time) == arrival + outgoing) if selected.destination_poi_id else day.return_arrival_time is None, 'return_arrival')
        days.append({'date': str(day.date), 'poi_ids': [s.poi.id for s in day.stops],
                     'stay_minutes': sum(s.stay_minutes for s in day.stops), 'travel_minutes': travel,
                     'interstop_travel_minutes': travel - incoming - outgoing, 'origin_travel_minutes': incoming, 'destination_travel_minutes': outgoing,
                     'distance_km': round(distance, 6), 'last_departure': day.stops[-1].departure_time})
    if trip.travel_load is not None:
        load=trip.travel_load
        require(load.mode==request.mode and load.max_leg_travel_minutes==request.max_leg_travel_minutes and load.max_daily_travel_minutes==request.max_daily_travel_minutes, 'load_request')
        require(len(load.days)==len(days), 'load_days')
        for index, (measured, saved) in enumerate(zip(days, load.days)):
            require(saved.day_number==index+1 and saved.stay_minutes==measured['stay_minutes'] and saved.travel_minutes==measured['travel_minutes'], 'load_totals')
            factual_day=trip.days[index]
            legs=[factual_day.origin_segment,*[stop.travel_to_next for stop in factual_day.stops],factual_day.destination_segment]
            require(saved.longest_leg_minutes==max((leg.duration_min for leg in legs if leg),default=None), 'load_longest_leg')
            elapsed=measured['stay_minutes']+measured['travel_minutes']
            require(abs(saved.travel_share_of_scheduled-round(measured['travel_minutes']/elapsed,4))<1e-6, 'load_share')
            require(saved.travel_at_least_stay==(measured['travel_minutes']>=measured['stay_minutes']), 'load_attention')
            require(not saved.over_daily_minutes and not saved.violating_legs, 'load_violations')
    require(len(ids) == len(set(ids)), 'duplicate_poi')
    require(trip.budget.total is None and trip.budget.known_subtotal == 0 and bool(trip.budget.unknown_items), 'unknown_budget_lost')
    automatic_grouping = request.days > 1 and request.stops_per_day > 1
    require(bool(trip.optimization) == automatic_grouping, 'comparison_presence')
    route_bound = route_call_bound(expected)
    totals = {'distance_km': round(sum(d['distance_km'] for d in days), 6),
              'travel_minutes': sum(d['travel_minutes'] for d in days),
              'busiest_day_minutes': max(d['stay_minutes'] + d['travel_minutes'] for d in days)}
    comparison = trip.optimization
    improvement = None
    if comparison:
        metrics = comparison.result
        require(metrics.feasible and metrics.per_day_travel_minutes == [d['travel_minutes'] for d in days], 'comparison_schedule')
        require(abs(metrics.distance_km - totals['distance_km']) < 1e-5, 'comparison_distance')
        require(metrics.travel_minutes == totals['travel_minutes'] and metrics.busiest_day_minutes == totals['busiest_day_minutes'], 'comparison_totals')
        require(0 < comparison.route_queries <= route_bound, 'route_call_bound')
        improvement = {'baseline_feasible': comparison.baseline.feasible,
            'travel_minutes_saved': comparison.baseline.travel_minutes - metrics.travel_minutes,
            'distance_km_saved': round(comparison.baseline.distance_km - metrics.distance_km, 6),
            'busiest_day_minutes_saved': comparison.baseline.busiest_day_minutes - metrics.busiest_day_minutes}
    unmatched = [item['id'] for item in evidence if not (item['name_contains_keyword'] or item['category_contains_keyword'])]
    other_cities = [item['id'] for item in evidence if item['city'] and item['city'].removesuffix('市') != request.city.removesuffix('市')]
    missing_cities = [item['id'] for item in evidence if not item['city']]
    observations = quality_observations(trip, days)
    return {'itinerary_id': trip.id, 'days': days, 'missing_fields': dict(sorted(missing.items())),
            'budget_total': trip.budget.total, 'unknown_budget_items': len(trip.budget.unknown_items),
            'route_queries': comparison.route_queries if comparison else None,
            'route_query_upper_bound': route_bound, 'route_count_basis': 'backend_matrix_count' if comparison else 'upper_bound_only',
            'grouping_applied': comparison.applied if comparison else False,
            'grouping_reason': comparison.reason if comparison else 'not_applicable',
            'totals': totals, 'improvement': improvement, 'poi_evidence': evidence,
            'keyword_evidence': {'method': 'literal_name_or_category', 'matched': len(evidence) - len(unmatched), 'total': len(evidence), 'unmatched_ids': unmatched},
            'different_reported_city_ids': other_cities, 'missing_reported_city_ids': missing_cities,
            'quality_observations': observations,
            'review_required': bool(unmatched or other_cities or missing_cities or observations['attention'])}


def compare_transports(cases):
    pairs = {}
    for case in cases:
        if 'scenario' in case:
            pairs.setdefault(case['scenario'], {})[case['transport']] = case
    comparisons = []
    for scenario, pair in pairs.items():
        if 'direct' not in pair or 'mcp' not in pair:
            continue
        a, b = pair['direct'], pair['mcp']
        comparable = a.get('passed') and b.get('passed')
        comparisons.append({'scenario': scenario, 'both_succeeded': bool(comparable),
            'same_ordered_poi_ids': [d['poi_ids'] for d in a['days']] == [d['poi_ids'] for d in b['days']] if comparable else None,
            'same_route_totals': a['totals'] == b['totals'] if comparable else None})
    return comparisons


def finalize_report(report):
    cases = report['cases']
    report['planning_success_count'] = sum(case.get('status') == 'succeeded' for case in cases)
    report['planning_failure_count'] = sum(case.get('status') in {'failed', 'timed_out', 'cancelled'} for case in cases)
    report['planning_unknown_count'] = report['expected_cases'] - report['planning_success_count'] - report['planning_failure_count']
    report['integrity_rejection_count'] = sum(case.get('status') == 'succeeded' and not case['passed'] for case in cases)
    report['failure_counts'] = dict(Counter(case.get('error_code', 'unknown') for case in cases if not case['passed']))
    report['review_required'] = any(case.get('review_required') for case in cases)
    report['subjective_quality_assessment'] = 'not_assessed'
    report['travel_attention_case_count'] = sum(bool(case.get('quality_observations', {}).get('attention')) for case in cases)
    report['transport_comparisons'] = compare_transports(cases)
    report['passed'] = len(cases) == report['expected_cases'] and all(case['passed'] for case in cases) and report['services_stopped_gracefully']
    return report


def run_case(client, request, transport):
    started = time.monotonic()
    response = client.post('/tasks', json=request)
    response.raise_for_status()
    task_id = response.json()['id']
    deadline = time.monotonic() + 210
    try:
        while time.monotonic() < deadline:
            response = client.get(f'/tasks/{task_id}')
            response.raise_for_status()
            task = response.json()
            if task['status'] not in {'queued', 'running'}:
                break
            time.sleep(.5)
        else:
            return {'passed': False, 'error_code': 'verification_deadline', 'task_id': task_id}
        if task['status'] != 'succeeded':
            from travel.schemas import Error
            error = Error.model_validate(task['error']) if task.get('error') else None
            require(task.get('itinerary_id') is None, 'failed_task_has_itinerary')
            return {'passed': False, 'status': task['status'], 'error_code': error.code if error else None, 'task_id': task_id,
                'retry_available': task.get('retry_available'), 'no_partial_itinerary': True,
                'time_constraints': error.time_constraints.model_dump(mode='json') if error and error.time_constraints else None,
                'travel_constraints': error.travel_constraints.model_dump(mode='json') if error and error.travel_constraints else None}
        try:
            response = client.get(f"/itineraries/{task['itinerary_id']}")
            response.raise_for_status()
            summary = summarize(response.json(), request)
            response = client.get(f'/tasks/{task_id}/events')
            response.raise_for_status()
            stages = [event['stage'] for event in response.json()['items']]
            require('validated' in stages, 'validation_event_missing')
            require(('tool_connected' in stages) == (transport == 'mcp'), 'transport_evidence')
            return {'passed': True, 'status': 'succeeded', 'task_id': task_id, 'seconds': round(time.monotonic() - started, 2), 'stages': stages, **summary}
        except Exception as error:
            # A completed task can still fail the inspector. Keep these counts separate.
            return {'passed': False, 'status': 'succeeded', 'task_id': task_id, 'error_code': 'quality_rejected',
                'check': str(error) if type(error) is ValueError else type(error).__name__}
    finally:
        # Terminal cancel is harmless; a failed read or deadline must not leave work running.
        client.post(f'/tasks/{task_id}/cancel').raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-amap', action='store_true')
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--profile', choices=['smoke', 'expanded', 'diverse'], default='smoke')
    parser.add_argument('--transport', choices=['direct', 'mcp', 'both'], default='both')
    parser.add_argument('--max-provider-calls', type=int, default=150, help='Preflight upper limit, 1–150; never an automatic retry budget')
    parser.add_argument('--dry-run', action='store_true', help='Print the fixed scenarios/bounds without reading credentials or starting services')
    parser.add_argument('--output', type=Path, default=Path('artifacts/live-quality/report.json'))
    args = parser.parse_args()
    selected = scenarios(args.profile, args.date)
    transports = ('direct', 'mcp') if args.transport == 'both' else (args.transport,)
    maximum = sum(case['maximum_provider_calls'] for case in selected) * len(transports)
    if not 0 < args.max_provider_calls <= 150 or maximum > args.max_provider_calls:
        parser.error(f'Selected scenarios require an upper budget of {maximum}; refused before starting services')
    if args.dry_run:
        print(json.dumps({'dry_run': True, 'profile': args.profile, 'transports': transports,
            'maximum_provider_calls': maximum, 'scenarios': selected}, ensure_ascii=False, indent=2))
        return 0
    if not args.live_amap:
        parser.error('Actual provider calls require explicit --live-amap')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('Report must be inside the ignored artifacts directory')
    env = dict(os.environ)
    settings = dotenv_values(ROOT / 'backend/.env')
    key = env.get('AMAP_KEY') or env.get('AMAP_WEB_KEY') or settings.get('AMAP_KEY') or settings.get('AMAP_WEB_KEY')
    if not key:
        raise SystemExit('Authorized Amap Web key is required; no fallback is available.')
    # Keep model calls and map SDK secrets outside these API/worker processes.
    for name in ('AMAP_KEY', 'AMAP_JS_KEY', 'AMAP_JS_SECURITY_CODE', 'DASHSCOPE_API_KEY', 'OPENAI_API_KEY', 'TRAVEL_LLM_API_KEY'):
        env[name] = ''
    # A live report must not silently target an overridden/mock provider origin.
    env.update(AMAP_WEB_KEY=key, AMAP_WEB_BASE_URL='https://restapi.amap.com', TRAVEL_PRODUCTION='1', TRAVEL_AUTH_MODE='local', TRAVEL_COOKIE_SECURE='0',
               TRAVEL_AGENT_ENABLED='0', LLM_INTENT_DISABLE_LLM='1', PYTHONIOENCODING='utf-8',
               TRAVEL_TASK_TIMEOUT='180', TRAVEL_SESSION_TTL='28800', TRAVEL_SESSION_IDLE_TTL='1800')
    report = {'live_provider': 'amap', 'recorded_at': datetime.now(timezone.utc).isoformat(), 'profile': args.profile,
              'pass_scope': 'schema_provenance_schedule_not_subjective_relevance', 'expected_cases': len(selected) * len(transports),
              'maximum_provider_calls': maximum, 'isolated_database': True, 'cases': [], 'services_stopped_gracefully': True}
    (ROOT / '.tmp').mkdir(exist_ok=True)
    for transport in transports:
        with tempfile.TemporaryDirectory(prefix='live-quality-', dir=ROOT / '.tmp') as directory:
            directory = Path(directory)
            stop = directory / 'stop'
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            env.update(TRAVEL_TOOL_TRANSPORT=transport, TRAVEL_DB_PATH=str(directory / 'quality.sqlite3'))
            with (directory / 'api.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, 'scripts/verification_server.py', '--port', str(port), '--stop-file', str(stop)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    with httpx.Client(base_url=f'http://127.0.0.1:{port}/api/v1/travel', timeout=20, trust_env=False) as client:
                        deadline = time.monotonic() + 25
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise RuntimeError('service_exited')
                            try:
                                ready = client.get('/capabilities')
                                ready.raise_for_status()
                                require(ready.json()['configured'] and ready.json()['tool_transport'] == transport, 'capabilities_mismatch')
                                break
                            except httpx.ConnectError:
                                time.sleep(.1)
                        else:
                            raise RuntimeError('service_start_deadline')
                        for scenario in selected:
                            request = scenario['request']
                            try:
                                result = run_case(client, request, transport)
                            except ValueError as error:
                                result = {'passed': False, 'error_code': 'quality_rejected', 'check': str(error) if type(error) is ValueError else type(error).__name__}
                            except Exception as error:
                                # Never print exception messages containing upstream URLs or credentials.
                                result = {'passed': False, 'error_code': type(error).__name__}
                            report['cases'].append({'transport': transport, **scenario, **result})
                            print(f"{transport}/{scenario['scenario']}: {'passed' if result['passed'] else result['error_code']}", flush=True)
                except Exception as error:
                    report['cases'].append({'transport': transport, 'passed': False, 'error_code': type(error).__name__})
                finally:
                    stop.touch()
                    try:
                        process.wait(timeout=15)
                        if process.returncode != 0:
                            report['services_stopped_gracefully'] = False
                    except subprocess.TimeoutExpired:
                        report['services_stopped_gracefully'] = False
                        process.terminate()
                        process.wait(timeout=5)
    finalize_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Live quality report: {output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
