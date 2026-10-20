"""Offline TEST ONLY inputs exercise the live report's rejection gates."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend'))
from verify_live_quality import summarize
from test_travel import FixtureProvider
from travel.planner import plan
from travel.schemas import PlanRequest, Source


class ReportInputProvider(FixtureProvider):
    # Amap labels here are deliberate TEST ONLY inputs to the validator.
    # This provider is never imported by the opt-in live runner or production.
    def search(self, *_):
        return [self.detail('fixture-' + letter) for letter in 'abcd']

    def detail(self, poi_id):
        poi = super().detail(poi_id)
        poi.source = Source(provider='amap')
        poi.missing_fields = ['city', 'address', 'category', 'rating', 'average_spend', 'opening_hours']
        return poi

    def route(self, origin, destination, mode):
        segment = super().route(origin, destination, mode)
        segment.source = Source(provider='amap')
        return segment


class LiveReportTests(unittest.TestCase):
    def setUp(self):
        self.request = {'city': 'TEST ONLY 城市', 'query': 'TEST ONLY 公园', 'start_date': '2026-10-20',
                        'days': 2, 'stops_per_day': 2, 'stay_minutes': 30, 'day_start': '09:00', 'day_end': '22:00', 'mode': 'walking'}
        self.raw = plan(PlanRequest.model_validate(self.request), lambda *_: None,
                        provider=ReportInputProvider()).model_dump(mode='json')

    def test_unknown_fields_and_complete_real_route_shape(self):
        result = summarize(self.raw, self.request)
        self.assertIsNone(result['budget_total'])
        self.assertEqual(result['missing_fields']['rating'], 4)
        self.assertEqual([day['travel_minutes'] for day in result['days']], [37, 37])

    def test_rejects_missing_provenance_and_markers(self):
        for field in ('source', 'missing_fields'):
            with self.subTest(field=field):
                raw = deepcopy(self.raw)
                raw['days'][0]['stops'][0]['poi'][field] = {'provider': 'user_input'} if field == 'source' else []
                with self.assertRaises(ValueError):
                    summarize(raw, self.request)

    def test_rejects_bad_dates_schedule_and_route_links(self):
        for change in ('date', 'arrival', 'route'):
            with self.subTest(change=change):
                raw = deepcopy(self.raw)
                if change == 'date': raw['days'][1]['date'] = '2026-10-20'
                if change == 'arrival': raw['days'][0]['stops'][1]['arrival_time'] = '09:00'
                if change == 'route': raw['days'][0]['stops'][0]['travel_to_next']['destination_id'] = 'TEST ONLY wrong'
                with self.assertRaises(ValueError):
                    summarize(raw, self.request)

    def test_rejects_fabricated_zero_cost_and_request_changes(self):
        for change in ('budget', 'station', 'transport', 'request'):
            with self.subTest(change=change):
                raw = deepcopy(self.raw)
                if change == 'budget': raw['budget']['total'] = 0
                if change == 'station': raw['days'][0]['stops'][0]['user_cost'] = 0
                if change == 'transport': raw['days'][0]['stops'][0]['travel_to_next']['total_cost'] = 0
                if change == 'request': raw['request']['mode'] = 'driving'
                with self.assertRaises(ValueError):
                    summarize(raw, self.request)


if __name__ == '__main__':
    unittest.main()
