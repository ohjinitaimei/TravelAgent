"""TEST ONLY matrices and isolated API records; never a production fallback."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_travel import FixtureProvider, fixture_worker, PAYLOAD
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import Itinerary, PlanRequest, Task

REQUEST = {**PAYLOAD, 'day_origin_poi_id': 'home', 'day_destination_poi_id': 'hotel'}


class EndpointProvider(FixtureProvider):
    def __init__(self):
        self.details, self.routes, self.searches = [], [], 0
    def search(self, *_):
        self.searches += 1
        return [FixtureProvider.detail(self, 'fixture-' + letter) for letter in 'abcd']
    def detail(self, poi_id):
        self.details.append(poi_id)
        return super().detail(poi_id)
    def route(self, a, b, mode):
        self.routes.append((a.id, b.id))
        leg = super().route(a, b, mode)
        distance, duration = {
            ('home', 'fixture-a'): (5, 10), ('home', 'fixture-b'): (1, 7),
            ('fixture-a', 'fixture-b'): (2, 13), ('fixture-b', 'fixture-a'): (3, 17),
            ('fixture-a', 'hotel'): (2, 11), ('fixture-b', 'hotel'): (4, 23),
        }.get((a.id, b.id), (6, 19))
        leg.distance_km, leg.duration_min = distance, duration
        return leg


def boundary_stall_worker(payload, output):
    class Blocked(EndpointProvider):
        def route(self, a, b, mode):
            if a.id == 'home': time.sleep(30)
            return super().route(a, b, mode)
    value=plan(PlanRequest.model_validate(payload['request']),lambda stage,message:output.put({'kind':'event','stage':stage,'message':message}),provider=Blocked())
    output.put({'kind':'result','data':value.model_dump(mode='json')})


class EndpointTests(unittest.TestCase):
    def test_factual_origin_seeds_existing_sort_and_both_legs_shift_schedule(self):
        trip = plan(PlanRequest.model_validate(REQUEST), lambda *_: None, provider=EndpointProvider())
        day = trip.days[0]
        self.assertEqual([s.poi.id for s in day.stops], ['fixture-b', 'fixture-a'])
        self.assertEqual(day.stops[0].arrival_time, '09:07')
        self.assertEqual(day.stops[1].arrival_time, '10:24')
        self.assertEqual(day.return_arrival_time, '11:35')
        self.assertEqual(day.origin_departure_time, '09:00')
        self.assertIsNone(day.stops[-1].travel_to_next)
        self.assertEqual(day.destination_segment.origin_id, 'fixture-a')
        self.assertIsNone(trip.budget.total)
        self.assertIn('末站至返回地：完整交通费用', trip.budget.unknown_items)

    def test_manual_order_remains_unchanged_with_directional_boundary_facts(self):
        trip = plan(PlanRequest.model_validate(REQUEST), lambda *_: None, provider=EndpointProvider(),
                    poi_ids_by_day=[['fixture-a', 'fixture-b']], optimize_order=False)
        self.assertEqual(trip.days[0].stops[0].arrival_time, '09:10')
        self.assertEqual(trip.days[0].return_arrival_time, '11:46')
        self.assertEqual(trip.days[0].origin_segment.origin_id, 'home')
        self.assertEqual(trip.days[0].destination_segment.destination_id, 'hotel')

    def test_one_sided_boundaries_preserve_the_unselected_side_semantics(self):
        for origin, destination, arrival, end in [('home', None, '09:10', None), (None, 'hotel', '09:00', '11:36')]:
            with self.subTest(origin=origin):
                trip = plan(PlanRequest.model_validate({**REQUEST, 'day_origin_poi_id': origin, 'day_destination_poi_id': destination}),
                            lambda *_: None, provider=EndpointProvider(), poi_ids_by_day=[['fixture-a', 'fixture-b']], optimize_order=False)
                self.assertEqual(trip.days[0].stops[0].arrival_time, arrival)
                self.assertEqual(trip.days[0].return_arrival_time, end)

    def test_same_adjacent_poi_has_no_fabricated_route_or_duplicate_detail(self):
        provider = EndpointProvider()
        trip = plan(PlanRequest.model_validate({**REQUEST, 'stops_per_day': 1, 'day_origin_poi_id': 'fixture-a', 'day_destination_poi_id': 'fixture-a'}),
                    lambda *_: None, provider=provider, poi_ids_by_day=[['fixture-a']])
        self.assertEqual(provider.details, ['fixture-a'])
        self.assertEqual(provider.routes, [])
        self.assertIsNone(trip.days[0].origin_segment)
        self.assertIsNone(trip.days[0].destination_segment)
        self.assertEqual(trip.days[0].return_arrival_time, '10:00')

    def test_single_day_maximum_budgets_and_directed_request_local_reuse(self):
        for editing, bound in [(False, 23), (True, 26)]:
            with self.subTest(editing=editing):
                provider = EndpointProvider()
                options = {'poi_ids_by_day': [['fixture-a', 'fixture-b', 'fixture-c', 'fixture-d']]} if editing else {}
                plan(PlanRequest.model_validate({**REQUEST, 'stops_per_day': 4}), lambda *_: None, provider=provider, **options)
                self.assertEqual(provider.searches + len(provider.details) + len(provider.routes), bound)
                self.assertEqual(len(provider.routes), len(set(provider.routes)))
                self.assertIn(('fixture-a', 'fixture-b'), provider.routes)
                self.assertIn(('fixture-b', 'fixture-a'), provider.routes)

    def test_return_alone_exceeds_end_and_diagnostics_explain_all_four_parts(self):
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate({**REQUEST, 'day_end': '11:30'}), lambda *_: None,
                 provider=EndpointProvider(), poi_ids_by_day=[['fixture-a', 'fixture-b']], optimize_order=False)
        failure = caught.exception
        self.assertEqual(failure.code, 'time_constraint_exceeded')
        day = failure.time_constraints.days[0]
        self.assertEqual((day.stay_minutes, day.travel_minutes, day.origin_travel_minutes, day.destination_travel_minutes), (120, 13, 10, 23))
        self.assertEqual((day.required_minutes, day.overrun_minutes), (166, 16))

    def test_very_long_incoming_route_cannot_wrap_the_clock_into_a_feasible_day(self):
        class LongIncoming(EndpointProvider):
            def route(self, a, b, mode):
                leg = super().route(a, b, mode)
                if a.id == 'home': leg.duration_min = 10_000
                return leg
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate(REQUEST), lambda *_: None, provider=LongIncoming())
        self.assertGreater(caught.exception.time_constraints.days[0].required_minutes, 10_000)

    def test_missing_boundary_route_fails_without_estimation(self):
        class MissingRoute(EndpointProvider):
            def route(self, a, b, mode):
                if b.id == 'hotel': raise TravelFailure('route_unavailable', 'TEST ONLY unavailable')
                return super().route(a, b, mode)
        with patch('services.route_planner._simple_estimate_distance', side_effect=AssertionError('No estimates')):
            with self.assertRaises(TravelFailure) as caught:
                plan(PlanRequest.model_validate(REQUEST), lambda *_: None, provider=MissingRoute())
        self.assertEqual(caught.exception.code, 'route_unavailable')

    def test_blank_ids_are_rejected_before_provider_calls(self):
        for values in ({**REQUEST, 'day_origin_poi_id': ' '}, {**REQUEST, 'day_destination_poi_id': ''}):
            with self.subTest(values=values), self.assertRaises(ValidationError): PlanRequest.model_validate(values)

    def test_old_saved_json_remains_readable_without_inventing_boundaries(self):
        trip = plan(PlanRequest.model_validate(PAYLOAD), lambda *_: None, provider=FixtureProvider())
        raw = trip.model_dump(mode='json')
        for field in ('day_origin_poi_id', 'day_destination_poi_id'): raw['request'].pop(field)
        for field in ('origin_poi', 'destination_poi', 'origin_segment', 'destination_segment', 'origin_departure_time', 'return_arrival_time'): raw['days'][0].pop(field)
        old = Itinerary.from_saved_json(json.dumps(raw))
        self.assertIsNone(old.days[0].origin_poi)
        self.assertIsNone(old.days[0].return_arrival_time)
        self.assertEqual(old.days[0].stops[0].arrival_time, '09:00')


class LargeEndpointProvider(EndpointProvider):
    def search(self, *_):
        self.searches += 1
        pois = [FixtureProvider.detail(self, f'fixture-{i}') for i in range(12)]
        for i, poi in enumerate(pois): poi.longitude = 120 + (i % 3) * .5 + (i // 3) * .001
        return pois


class MultiDayEndpointTests(unittest.TestCase):
    def test_maximum_shared_endpoints_reserve_budget_and_explain_limited_candidates(self):
        provider = LargeEndpointProvider()
        request = PlanRequest.model_validate({**REQUEST, 'days': 3, 'stops_per_day': 4, 'stay_minutes': 10})
        with patch('services.route_planner._simple_estimate_distance', side_effect=AssertionError('No estimates')):
            trip = plan(request, lambda *_: None, provider=provider)
        self.assertEqual(provider.searches + len(provider.details) + len(provider.routes), 63)
        self.assertEqual(len(provider.routes), len(set(provider.routes)))
        self.assertEqual(trip.optimization.route_queries, 60)
        self.assertEqual(trip.optimization.candidate_route_limit, 37)
        self.assertTrue(trip.optimization.candidate_search_limited)
        self.assertEqual(trip.optimization.reason, 'tool_budget_limited')
        self.assertEqual(trip.optimization.candidates, [])
        for i, day in enumerate(trip.days):
            self.assertEqual(str(day.date), str(request.start_date.replace(day=request.start_date.day + i)))
            self.assertEqual(day.origin_departure_time, request.day_start)
            self.assertEqual(day.origin_poi.id, 'home')
            self.assertEqual(day.destination_poi.id, 'hotel')
            self.assertEqual(day.stops[0].arrival_time, '09:19')
            self.assertEqual(day.return_arrival_time, '11:15')
            self.assertIsNone(day.stops[-1].travel_to_next)
        self.assertIn('第 3 天：末站至返回地：完整交通费用', trip.budget.unknown_items)
        self.assertIsNone(trip.budget.total)

    def test_fixed_order_maximum_edit_queries_only_required_edges(self):
        provider = LargeEndpointProvider()
        groups = [[f'fixture-{day*4+i}' for i in range(4)] for day in range(3)]
        trip = plan(PlanRequest.model_validate({**REQUEST, 'days': 3, 'stops_per_day': 4, 'stay_minutes': 10}),
                    lambda *_: None, provider=provider, poi_ids_by_day=groups, optimize_order=False, parent_id='TEST ONLY source')
        self.assertEqual(provider.searches + len(provider.details) + len(provider.routes), 29)
        self.assertEqual([[s.poi.id for s in day.stops] for day in trip.days], groups)
        self.assertIsNone(trip.optimization)
        self.assertNotIn(('fixture-1', 'fixture-0'), provider.routes)

    def test_excessive_resort_is_rejected_without_any_provider_call(self):
        provider = LargeEndpointProvider()
        groups = [[f'fixture-{day*4+i}' for i in range(4)] for day in range(3)]
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate({**REQUEST, 'days': 3, 'stops_per_day': 4}),
                 lambda *_: None, provider=provider, poi_ids_by_day=groups, optimize_order=True)
        self.assertEqual(caught.exception.code, 'planning_budget_exceeded')
        self.assertEqual((provider.searches, provider.details, provider.routes), (0, [], []))

    def test_smaller_multiday_resort_and_uneven_fixed_order_remain_supported(self):
        for groups, optimize in [([['fixture-a', 'fixture-b'], ['fixture-c', 'fixture-d']], True),
                                 ([['fixture-a'], ['fixture-b', 'fixture-c', 'fixture-d']], False)]:
            with self.subTest(groups=groups):
                provider = EndpointProvider()
                trip = plan(PlanRequest.model_validate({**REQUEST, 'days': 2}), lambda *_: None,
                            provider=provider, poi_ids_by_day=groups, optimize_order=optimize)
                self.assertEqual([len(day.stops) for day in trip.days], [len(day) for day in groups])
                self.assertTrue(all(day.origin_departure_time == '09:00' for day in trip.days))
                self.assertLessEqual(len(provider.details) + len(provider.routes), 64)

    def test_multiday_conflict_identifies_each_day_and_includes_shared_return(self):
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate({**REQUEST, 'days': 2, 'day_end': '11:30'}), lambda *_: None,
                 provider=EndpointProvider(), poi_ids_by_day=[['fixture-a', 'fixture-b'], ['fixture-c', 'fixture-d']], optimize_order=False)
        diagnostics = caught.exception.time_constraints
        self.assertEqual([day.day_number for day in diagnostics.days], [1, 2])
        self.assertEqual([day.required_minutes for day in diagnostics.days], [166, 177])
        self.assertEqual(diagnostics.days[1].destination_travel_minutes, 19)

    def test_shared_point_that_is_a_visit_reuses_detail_and_never_fakes_adjacent_route(self):
        provider = EndpointProvider()
        trip = plan(PlanRequest.model_validate({**REQUEST, 'days': 2, 'stops_per_day': 1,
                    'day_origin_poi_id': 'fixture-a', 'day_destination_poi_id': 'fixture-a'}),
                    lambda *_: None, provider=provider, poi_ids_by_day=[['fixture-a'], ['fixture-b']], optimize_order=False)
        self.assertEqual(provider.details, ['fixture-a', 'fixture-b'])
        self.assertEqual(provider.routes, [('fixture-a', 'fixture-b'), ('fixture-b', 'fixture-a')])
        self.assertIsNone(trip.days[0].origin_segment)
        self.assertEqual(trip.days[1].return_arrival_time, '10:30')


@contextmanager
def api(timeout='180'):
    from main import app
    with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder, patch.dict(os.environ, {'TRAVEL_DB_PATH': str(Path(folder) / 'test.sqlite3'), 'TRAVEL_AUTH_MODE': 'local','TRAVEL_TASK_TIMEOUT':timeout}), patch('travel.tasks.run', fixture_worker), TestClient(app) as client:
        yield client, app


def result(client, response):
    assert response.status_code == 202, response.json()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        task = client.get('/api/v1/travel/tasks/' + response.json()['id']).json()
        if task['status'] not in {'queued', 'running'}:
            assert task['status'] == 'succeeded', task
            return client.get('/api/v1/travel/itineraries/' + task['itinerary_id']).json()
        time.sleep(.05)
    raise AssertionError('TEST ONLY task deadline')


class EndpointApiTests(unittest.TestCase):
    def test_blocked_boundary_calls_can_cancel_or_time_out_without_saving_partial_results(self):
        for action in ('cancel','timeout'):
            with self.subTest(action=action),api(timeout='4') as (client,_),patch('travel.tasks.run',boundary_stall_worker):
                response=client.post('/api/v1/travel/tasks',json=REQUEST)
                identifier=response.json()['id'];base='/api/v1/travel/tasks/'+identifier
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    if any(e['stage']=='boundary_routing' for e in client.get(base+'/events').json()['items']):break
                    time.sleep(.05)
                else:self.fail('Boundary stage not reached')
                if action=='cancel':self.assertEqual(client.post(base+'/cancel').status_code,200)
                while time.monotonic()<deadline:
                    task=client.get(base).json()
                    if task['status'] in {'cancelled','timed_out'}:break
                    time.sleep(.05)
                self.assertEqual(task['status'],'cancelled' if action=='cancel' else 'timed_out')
                self.assertIsNone(task['itinerary_id'])
                self.assertEqual(client.get('/api/v1/travel/itineraries').json()['total'],0)

    def test_adjustment_omission_preserves_null_clears_and_source_remains_unchanged(self):
        with api() as (client, _):
            parent = result(client, client.post('/api/v1/travel/tasks', json=REQUEST))
            path = '/api/v1/travel/itineraries/' + parent['id'] + '/adjust'
            edit = {'poi_ids_by_day': [['fixture-a', 'fixture-b']]}
            child = result(client, client.post(path, json=edit))
            self.assertEqual(child['request']['day_origin_poi_id'], 'home')
            cleared = result(client, client.post(path, json={**edit, 'day_origin_poi_id': None, 'day_destination_poi_id': None}))
            self.assertIsNone(cleared['days'][0]['origin_poi'])
            self.assertEqual(cleared['days'][0]['stops'][0]['arrival_time'], '09:00')
            self.assertEqual(client.get(path.removesuffix('/adjust')).json(), parent)

    def test_multiday_edit_admission_and_null_clearing_leave_source_intact(self):
        with api() as (client, app):
            parent = plan(PlanRequest.model_validate({**REQUEST, 'days': 3, 'stops_per_day': 4, 'stay_minutes': 10}),
                          lambda *_: None, provider=LargeEndpointProvider())
            app.state.travel.store.succeed(Task(id='TEST ONLY multiday', status='running'), parent)
            groups = [[s.poi.id for s in day.stops] for day in parent.days]
            path = '/api/v1/travel/itineraries/' + parent.id + '/adjust'
            with patch.object(app.state.travel, 'create') as create:
                response = client.post(path, json={'poi_ids_by_day': groups, 'optimize_order': True})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['error']['code'], 'planning_budget_exceeded')
                create.assert_not_called()
            child = result(client, client.post(path, json={'poi_ids_by_day': groups, 'day_destination_poi_id': None}))
            self.assertTrue(all(day['origin_poi']['id'] == 'home' and day['destination_poi'] is None for day in child['days']))
            self.assertEqual(client.get(path.removesuffix('/adjust')).json(), parent.model_dump(mode='json'))

    def test_legacy_receipt_null_equivalence_and_non_null_id_conflict(self):
        with api() as (client, app):
            request = PlanRequest.model_validate(PAYLOAD).model_dump(mode='json')
            for field in ('compare_poi_alternatives', 'day_origin_poi_id', 'day_destination_poi_id', 'day_endpoints', 'day_schedules', 'max_leg_travel_minutes', 'max_daily_travel_minutes'): request.pop(field)
            payload = {'request': request}
            fingerprint = hashlib.sha256(json.dumps({'payload': payload, 'retry_of': None}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            task = Task(id='test-only-old-receipt', status='failed')
            app.state.travel.store.register_task(task, payload, 'test-only-old-key', fingerprint)
            headers = {'Idempotency-Key': 'test-only-old-key'}
            response = client.post('/api/v1/travel/tasks', json={**PAYLOAD, 'day_origin_poi_id': None, 'max_leg_travel_minutes': None}, headers=headers)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['id'], task.id)
            self.assertEqual(client.post('/api/v1/travel/tasks', json={**PAYLOAD, 'day_origin_poi_id': 'home'}, headers=headers).status_code, 409)
            self.assertEqual(client.post('/api/v1/travel/tasks', json={**PAYLOAD, 'max_leg_travel_minutes': 30}, headers=headers).status_code, 409)


if __name__ == '__main__': unittest.main()
