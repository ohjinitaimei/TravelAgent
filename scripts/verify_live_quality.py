"""Opt-in, bounded real Amap quality checks through an isolated production API.

No fixture injection, model calls, production database access or automatic retries.
Four plans at most; each uses four POIs and at most twelve directed route calls.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
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


def summarize(raw, expected):
    """Reject invalid provenance/schedules before recording a passing sample."""
    from travel.schemas import Itinerary, PlanRequest
    trip = Itinerary.model_validate(raw)
    request = PlanRequest.model_validate(expected)
    require(trip.request == request, 'request_mismatch')
    require(len(trip.days) == request.days, 'day_count')
    ids, days, missing = [], [], Counter()
    minute = lambda value: int(value[:2]) * 60 + int(value[3:])
    for index, day in enumerate(trip.days):
        require(day.date == request.start_date + timedelta(days=index), 'day_date')
        require(len(day.stops) == request.stops_per_day, 'stop_count')
        arrival = minute(request.day_start)
        distance, travel = 0.0, 0
        for position, stop in enumerate(day.stops):
            ids.append(stop.poi.id)
            require(stop.poi.source.provider == 'amap', 'poi_provenance')
            require(datetime.fromisoformat(stop.poi.source.retrieved_at).tzinfo is not None, 'poi_timestamp')
            for field in ('city', 'address', 'category', 'rating', 'average_spend', 'opening_hours'):
                absent = getattr(stop.poi, field) is None
                require(absent == (field in stop.poi.missing_fields), 'missing_field_marker')
                if absent:
                    missing[field] += 1
            require(stop.stay_minutes == request.stay_minutes, 'stay_duration')
            require(stop.stay_source == 'user_input', 'stay_provenance')
            require(minute(stop.arrival_time) == arrival, 'arrival_schedule')
            arrival += stop.stay_minutes
            require(minute(stop.departure_time) == arrival, 'departure_schedule')
            require(arrival <= minute(request.day_end), 'day_end_exceeded')
            require(stop.user_cost is None and stop.cost_source is None, 'invented_station_cost')
            segment = stop.travel_to_next
            if position == len(day.stops) - 1:
                require(segment is None, 'unexpected_last_route')
            else:
                require(segment is not None, 'missing_route')
                require(segment.source.provider == 'amap', 'route_provenance')
                require(datetime.fromisoformat(segment.source.retrieved_at).tzinfo is not None, 'route_timestamp')
                require(segment.origin_id == stop.poi.id and segment.destination_id == day.stops[position + 1].poi.id, 'route_link')
                require(segment.mode == request.mode and bool(segment.polyline), 'route_mode_geometry')
                require(segment.total_cost is None, 'invented_transport_cost')
                travel += segment.duration_min
                distance += segment.distance_km
                arrival += segment.duration_min
        days.append({'date': str(day.date), 'poi_ids': [s.poi.id for s in day.stops],
                     'stay_minutes': sum(s.stay_minutes for s in day.stops), 'travel_minutes': travel,
                     'distance_km': round(distance, 6), 'last_departure': day.stops[-1].departure_time})
    require(len(ids) == len(set(ids)), 'duplicate_poi')
    require(trip.budget.total is None and trip.budget.known_subtotal == 0 and bool(trip.budget.unknown_items), 'unknown_budget_lost')
    require(trip.optimization is not None, 'missing_comparison')
    metrics = trip.optimization.result
    require(metrics.feasible and metrics.per_day_travel_minutes == [d['travel_minutes'] for d in days], 'comparison_schedule')
    require(abs(metrics.distance_km - sum(d['distance_km'] for d in days)) < 1e-5, 'comparison_distance')
    require(0 < trip.optimization.route_queries <= 12, 'route_call_bound')
    return {'itinerary_id': trip.id, 'days': days, 'missing_fields': dict(sorted(missing.items())),
            'budget_total': trip.budget.total, 'unknown_budget_items': len(trip.budget.unknown_items),
            'route_queries': trip.optimization.route_queries, 'grouping_applied': trip.optimization.applied,
            'grouping_reason': trip.optimization.reason}


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
            return {'passed': False, 'status': task['status'], 'error_code': (task.get('error') or {}).get('code'), 'task_id': task_id}
        response = client.get(f"/itineraries/{task['itinerary_id']}")
        response.raise_for_status()
        summary = summarize(response.json(), request)
        response = client.get(f'/tasks/{task_id}/events')
        response.raise_for_status()
        stages = [event['stage'] for event in response.json()['items']]
        require('validated' in stages, 'validation_event_missing')
        require(('tool_connected' in stages) == (transport == 'mcp'), 'transport_evidence')
        return {'passed': True, 'task_id': task_id, 'seconds': round(time.monotonic() - started, 2), 'stages': stages, **summary}
    finally:
        # Terminal cancel is harmless; a failed read or deadline must not leave work running.
        client.post(f'/tasks/{task_id}/cancel').raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-amap', action='store_true', required=True)
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/live-quality/report.json'))
    args = parser.parse_args()
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
    report = {'live_provider': 'amap', 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'maximum_provider_calls': 52, 'isolated_database': True, 'cases': [], 'services_stopped_gracefully': True}
    (ROOT / '.tmp').mkdir(exist_ok=True)
    for transport in ('direct', 'mcp'):
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
                        for city, mode in (('南京', 'walking'), ('苏州', 'driving')):
                            request = {'city': city, 'query': '公园', 'start_date': str(args.date), 'days': 2,
                                       'stops_per_day': 2, 'stay_minutes': 30, 'day_start': '09:00', 'day_end': '22:00', 'mode': mode}
                            try:
                                result = run_case(client, request, transport)
                            except ValueError as error:
                                result = {'passed': False, 'error_code': 'quality_rejected', 'check': str(error) if type(error) is ValueError else type(error).__name__}
                            except Exception as error:
                                # Never print exception messages containing upstream URLs or credentials.
                                result = {'passed': False, 'error_code': type(error).__name__}
                            report['cases'].append({'transport': transport, 'request': request, **result})
                            print(f"{transport}/{city}/{mode}: {'passed' if result['passed'] else result['error_code']}", flush=True)
                except Exception as error:
                    report['cases'].append({'transport': transport, 'passed': False, 'error_code': type(error).__name__})
                finally:
                    stop.touch()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        report['services_stopped_gracefully'] = False
                        process.terminate()
                        process.wait(timeout=5)
    report['passed'] = len(report['cases']) == 4 and all(case['passed'] for case in report['cases']) and report['services_stopped_gracefully']
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Live quality report: {output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
