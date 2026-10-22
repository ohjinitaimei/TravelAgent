"""TEST ONLY geography and directed traffic; never imported by production."""
from collections import Counter
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from services import poi_ranker, route_planner
from travel.planner import legacy, plan
from travel.provider import TravelFailure
from travel.schemas import Itinerary, PlanRequest, Poi, Point, Segment, Source

REQUEST = {'city': 'TEST ONLY', 'query': 'TEST ONLY geographic', 'start_date': '2026-10-20',
           'days': 2, 'stops_per_day': 2, 'stay_minutes': 30, 'day_start': '09:00', 'day_end': '20:00'}


class GeographicFixture:
    def __init__(self, count=4, near=(1, 10), far=(20, 100), asymmetric=False, fail_near=False):
        self.calls = []
        self.near, self.far, self.asymmetric, self.fail_near = near, far, asymmetric, fail_near
        regions = 2 if count == 4 else 3
        self.pois = [Poi(id=f'test-{i:02}', name='TEST ONLY geographic', longitude=120 + (i % regions) * .5 + (i // regions) * .001,
                         latitude=30, source=Source(provider='user_input')) for i in range(count)]

    def search(self, *_): return self.pois

    def detail(self, identifier): return next(p for p in self.pois if p.id == identifier)

    def route(self, a, b, mode):
        self.calls.append((a.id, b.id, mode))
        near = abs(a.longitude - b.longitude) < .1
        if near and self.fail_near:
            raise TravelFailure('provider_timeout', 'TEST ONLY unavailable candidate route', True, 504)
        distance, duration = self.near if near else self.far
        if self.asymmetric and a.id > b.id:
            distance, duration = distance + .1, duration + 3
        return Segment(origin_id=a.id, destination_id=b.id, mode=mode, distance_km=distance, duration_min=duration,
                       source=Source(provider='user_input'), polyline=[Point(longitude=a.longitude, latitude=a.latitude), Point(longitude=b.longitude, latitude=b.latitude)])


def geographic_fixture_worker(payload, output):
    result = plan(PlanRequest.model_validate(payload['request']),
                  lambda stage, message: output.put({'kind': 'event', 'stage': stage, 'message': message}),
                  provider=GeographicFixture(), poi_ids_by_day=payload.get('poi_ids_by_day'),
                  optimize_order=payload.get('optimize_order', True), parent_id=payload.get('parent_id'))
    output.put({'kind': 'result', 'data': result.model_dump(mode='json')})


class DayGroupingTests(unittest.TestCase):
    def test_real_matrix_comparison_reduces_travel_and_reuses_existing_algorithms(self):
        fixture = GeographicFixture(asymmetric=True)
        with (patch.object(route_planner, '_simple_estimate_distance', side_effect=AssertionError('No traffic estimates')),
             patch.object(poi_ranker, 'rank_pois', wraps=poi_ranker.rank_pois) as ranker,
             patch.object(route_planner, '_build_route_stops', wraps=route_planner._build_route_stops) as scheduler):
            trip = plan(PlanRequest(**REQUEST), lambda *_: None, provider=fixture)
        self.assertEqual(ranker.call_count, 1)
        self.assertEqual(scheduler.call_count, 2 * (1 + len(trip.optimization.candidates)))
        summary = trip.optimization
        self.assertTrue(summary.applied)
        self.assertEqual(summary.reason, 'improved')
        self.assertEqual(summary.baseline.travel_minutes, 200)
        self.assertEqual(summary.result.travel_minutes, 20)
        self.assertEqual(summary.baseline.distance_km, 40)
        self.assertEqual(summary.result.distance_km, 2)
        self.assertCountEqual([[s.poi.id for s in d.stops] for d in trip.days], [['test-00', 'test-02'], ['test-01', 'test-03']])
        self.assertEqual(summary.route_queries, 12)
        self.assertTrue(all(count == 1 for count in Counter(fixture.calls).values()))
        self.assertIn(('test-02', 'test-00', 'walking'), fixture.calls)
        self.assertEqual(trip.days[0].stops[1].arrival_time, '09:40')

    def test_geographically_close_but_worse_roads_retain_verified_baseline(self):
        trip = plan(PlanRequest(**REQUEST), lambda *_: None, provider=GeographicFixture(near=(30, 130)))
        self.assertFalse(trip.optimization.applied)
        self.assertEqual(trip.optimization.reason, 'baseline_preferred')
        self.assertEqual(trip.optimization.result, trip.optimization.baseline)
        self.assertTrue(any(c.travel_minutes > trip.optimization.result.travel_minutes for c in trip.optimization.candidates))
        self.assertEqual([[s.poi.id for s in d.stops] for d in trip.days], trip.optimization.baseline_poi_ids_by_day)

    def test_feasible_candidate_rescues_original_time_violation(self):
        trip = plan(PlanRequest(**{**REQUEST, 'day_end': '10:30'}), lambda *_: None, provider=GeographicFixture())
        self.assertFalse(trip.optimization.baseline.feasible)
        self.assertTrue(trip.optimization.result.feasible)
        self.assertEqual(trip.optimization.reason, 'feasible_candidate')
        self.assertEqual(trip.days[0].stops[-1].departure_time, '10:10')

    def test_both_infeasible_fail_without_returning_invalid_schedule(self):
        with self.assertRaises(TravelFailure) as error:
            plan(PlanRequest(**{**REQUEST, 'day_end': '09:45'}), lambda *_: None, provider=GeographicFixture())
        self.assertEqual(error.exception.code, 'time_constraint_exceeded')

    def test_daily_stay_imbalance_prevents_a_worse_busiest_day(self):
        request = PlanRequest(**{**REQUEST, 'stay_minutes': 10, 'day_end': '23:00', 'stay_minutes_by_poi': {'test-00': 300, 'test-02': 300}})
        trip = plan(request, lambda *_: None, provider=GeographicFixture())
        self.assertTrue(any(c.travel_minutes < trip.optimization.baseline.travel_minutes and
                            c.busiest_day_minutes > trip.optimization.baseline.busiest_day_minutes for c in trip.optimization.candidates))
        self.assertFalse(trip.optimization.applied)

    def test_user_grouping_is_preserved_with_or_without_daily_sorting(self):
        for optimize in (True, False):
            fixture = GeographicFixture()
            groups = [['test-03', 'test-00'], ['test-01', 'test-02']]
            trip = plan(PlanRequest(**REQUEST), lambda *_: None, provider=fixture, poi_ids_by_day=groups, optimize_order=optimize)
            self.assertEqual([[s.poi.id for s in d.stops] for d in trip.days], groups)
            self.assertIsNone(trip.optimization)
            self.assertEqual(len(fixture.calls), 4 if optimize else 2)
            if not optimize:
                self.assertEqual(fixture.calls, [('test-03', 'test-00', 'walking'), ('test-01', 'test-02', 'walking')])
        unsorted = plan(PlanRequest(**REQUEST), lambda *_: None, provider=GeographicFixture(), optimize_order=False)
        self.assertIsNone(unsorted.optimization)
        self.assertEqual([[s.poi.id for s in d.stops] for d in unsorted.days], [['test-00', 'test-01'], ['test-02', 'test-03']])

    def test_costs_and_per_poi_stay_follow_the_same_poi_after_exchange(self):
        request = PlanRequest(**{**REQUEST, 'user_prices': {'test-00': 0, 'test-02': 25}, 'stay_minutes_by_poi': {'test-00': 20, 'test-02': 40}})
        trip = plan(request, lambda *_: None, provider=GeographicFixture())
        self.assertTrue(trip.optimization.applied)
        by_id = {s.poi.id: s for d in trip.days for s in d.stops}
        self.assertEqual(by_id['test-00'].user_cost, 0)
        self.assertEqual(by_id['test-02'].stay_minutes, 40)
        self.assertEqual(trip.budget.known_subtotal, 25)
        self.assertIsNone(trip.budget.total)

    def test_maximum_plan_is_deterministic_and_bounds_directed_route_calls(self):
        fixture = GeographicFixture(count=12)
        request = PlanRequest(**{**REQUEST, 'days': 3, 'stops_per_day': 4, 'stay_minutes': 10, 'day_end': '23:00'})
        internal = [legacy(p, request) for p in fixture.pois]
        groups = [internal[i:i+4] for i in range(0, 12, 4)]
        proposed = route_planner.propose_day_group_candidates(groups)
        self.assertEqual(proposed, route_planner.propose_day_group_candidates(groups))
        self.assertGreaterEqual(len(proposed), 1)
        for partition in proposed:
            self.assertEqual([len(day) for day in partition], [4, 4, 4])
            self.assertEqual(sorted(p.id for day in partition for p in day), sorted(p.id for p in internal))
        trip = plan(request, lambda *_: None, provider=fixture)
        self.assertLessEqual(len(fixture.calls), 48)
        self.assertEqual(len(fixture.calls), len(set(fixture.calls)))
        self.assertEqual(trip.optimization.route_queries, len(fixture.calls))

    def test_single_day_and_single_stop_days_do_not_add_queries(self):
        for days, stops in ((1, 2), (2, 1)):
            fixture = GeographicFixture()
            trip = plan(PlanRequest(**{**REQUEST, 'days': days, 'stops_per_day': stops}), lambda *_: None, provider=fixture)
            self.assertIsNone(trip.optimization)
            self.assertEqual(len(fixture.calls), 2 if days == 1 else 0)

    def test_no_geographic_change_uses_original_matrix_only(self):
        fixture = GeographicFixture()
        fixture.pois = [fixture.pois[i] for i in (0, 2, 1, 3)]
        # Give the existing ranker a fixed ranking representing a clustered result.
        request = PlanRequest(**REQUEST)
        ranked = [{'poi': legacy(p, request)} for p in fixture.pois]
        with patch.object(poi_ranker, 'rank_pois', return_value=ranked):
            trip = plan(request, lambda *_: None, provider=fixture)
        self.assertEqual(trip.optimization.reason, 'no_geographic_change')
        self.assertEqual(trip.optimization.candidates, [])
        self.assertEqual(len(fixture.calls), 4)

    def test_missing_candidate_route_is_an_error_not_an_estimated_fallback(self):
        with self.assertRaises(TravelFailure) as error:
            plan(PlanRequest(**REQUEST), lambda *_: None, provider=GeographicFixture(fail_near=True))
        self.assertEqual(error.exception.code, 'provider_timeout')

    def test_old_itinerary_remains_readable_without_comparison(self):
        trip = plan(PlanRequest(**{**REQUEST, 'days': 1}), lambda *_: None, provider=GeographicFixture())
        value = trip.model_dump(mode='json')
        value.pop('optimization')
        self.assertIsNone(Itinerary.model_validate(value).optimization)

    def test_alternative_candidate_can_win_when_best_geometry_has_a_road_detour(self):
        class DetourFixture(GeographicFixture):
            def __init__(self):
                super().__init__()
                for poi, (lng, lat) in zip(self.pois, [(120, 30), (120.02, 30.02), (120, 30.02), (120.02, 30)]):
                    poi.longitude, poi.latitude = lng, lat

            def route(self, a, b, mode):
                segment = super().route(a, b, mode)
                pair = frozenset((a.id, b.id))
                if pair in (frozenset(('test-00', 'test-01')), frozenset(('test-02', 'test-03'))):
                    distance, duration = 20, 100
                elif pair in (frozenset(('test-00', 'test-03')), frozenset(('test-01', 'test-02'))):
                    distance, duration = 30, 200
                else:
                    distance, duration = 1, 10
                return segment.model_copy(update={'distance_km': distance, 'duration_min': duration})

        fixture = DetourFixture()
        trip = plan(PlanRequest(**REQUEST), lambda *_: None, provider=fixture)
        self.assertTrue(trip.optimization.applied)
        self.assertEqual(len(trip.optimization.candidates), 2)
        self.assertEqual(trip.optimization.result.travel_minutes, 20)
        self.assertEqual(trip.optimization.route_queries, 12)
        self.assertEqual(len(fixture.calls), len(set(fixture.calls)))


if __name__ == '__main__':
    unittest.main()
