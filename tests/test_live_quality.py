"""Offline TEST ONLY inputs exercise the live report's rejection gates."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend'))
from verify_live_quality import summarize, scenarios, provider_call_bound, finalize_report, main
from test_travel import FixtureProvider
from travel.planner import plan
from travel.schemas import PlanRequest, Source


class ReportInputProvider(FixtureProvider):
    # Amap labels here are deliberate TEST ONLY inputs to the validator.
    # This provider is never imported by the opt-in live runner or production.
    def __init__(self, count=4):
        self.count=count

    def search(self, *_):
        return [self.detail('fixture-' + chr(ord('a')+index)) for index in range(self.count)]

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

    def test_daily_travel_load_slack_and_longest_leg_use_saved_facts(self):
        observed = summarize(self.raw, self.request)['quality_observations']
        self.assertEqual(observed['day_load_spread_minutes'], 0)
        day = observed['days'][0]
        self.assertEqual((day['available_minutes'], day['scheduled_minutes'], day['remaining_minutes']), (780, 97, 683))
        self.assertEqual(day['travel_share_of_scheduled'], .3814)
        self.assertEqual(day['longest_leg_minutes'], 37)
        self.assertEqual(len(day['legs']), 1)
        self.assertEqual(day['legs'][0]['source'], self.raw['days'][0]['stops'][0]['travel_to_next']['source'])
        self.assertEqual(day['legs'][0]['destination_id'], self.raw['days'][0]['stops'][1]['poi']['id'])

    def test_single_stop_day_has_no_route_not_an_invented_zero_minute_leg(self):
        request = {**self.request, 'days': 1, 'stops_per_day': 1}
        raw = plan(PlanRequest.model_validate(request), lambda *_: None, provider=ReportInputProvider()).model_dump(mode='json')
        day = summarize(raw, request)['quality_observations']['days'][0]
        self.assertEqual(day['travel_share_of_scheduled'], 0)
        self.assertIsNone(day['longest_leg_minutes'])
        self.assertEqual(day['legs'], [])
        self.assertEqual(day['remaining_minutes'], 750)

    def test_travel_attention_is_inclusive_and_does_not_reject_feasible_trips(self):
        class LongRouteProvider(ReportInputProvider):
            minutes = 60
            def route(self, *args):
                segment = super().route(*args)
                segment.duration_min = self.minutes
                return segment
        request = {**self.request, 'days': 1}
        for duration, attention in ((59, []), (60, [{'code': 'travel_at_least_stay', 'day_number': 1}])):
            with self.subTest(duration=duration):
                provider = LongRouteProvider(); provider.minutes = duration
                raw = plan(PlanRequest.model_validate(request), lambda *_: None, provider=provider).model_dump(mode='json')
                observed = summarize(raw, request)['quality_observations']
                self.assertEqual(observed['attention'], attention)
                self.assertEqual(observed['subjective_satisfaction'], 'not_assessed')

    def test_observations_do_not_mutate_source_or_claim_unmeasured_capabilities(self):
        original = deepcopy(self.raw)
        observed = summarize(self.raw, self.request)['quality_observations']
        self.assertEqual(self.raw, original)
        self.assertEqual(observed['scope'], 'saved_interstop_facts_only')
        self.assertFalse(observed['origin_return_included'])
        self.assertFalse(observed['future_opening_verified'])
        self.assertNotIn('score', observed)
        self.assertNotIn('satisfied', observed)

    def test_diverse_profile_adds_cities_and_respects_a_preflight_budget(self):
        cases = scenarios('diverse', '2026-10-23')
        self.assertEqual({case['request']['city'] for case in cases}, {'杭州', '北京', '成都'})
        self.assertEqual([case['maximum_provider_calls'] for case in cases], [31, 7, 13])
        self.assertEqual(sum(case['maximum_provider_calls'] for case in cases), 51)
        with patch.object(sys, 'argv', ['verify_live_quality.py', '--date', '2026-10-23', '--profile', 'diverse', '--transport', 'direct', '--max-provider-calls', '50', '--live-amap']), patch('verify_live_quality.subprocess.Popen') as start, patch('verify_live_quality.dotenv_values') as credentials, patch('sys.stderr'):
            with self.assertRaises(SystemExit) as caught:
                main()
            self.assertEqual(caught.exception.code, 2)
            start.assert_not_called(); credentials.assert_not_called()

    def test_integrity_success_with_attention_is_not_subjective_quality_approval(self):
        case = {'status': 'succeeded', 'passed': True, 'review_required': True,
                'quality_observations': {'attention': [{'code': 'travel_at_least_stay', 'day_number': 1}]}}
        result = finalize_report({'expected_cases': 1, 'services_stopped_gracefully': True, 'cases': [case]})
        self.assertTrue(result['passed'])
        self.assertTrue(result['review_required'])
        self.assertEqual(result['travel_attention_case_count'], 1)
        self.assertEqual(result['subjective_quality_assessment'], 'not_assessed')

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

    def test_single_day_requires_no_grouping_and_does_not_claim_measured_call_count(self):
        request={**self.request,'days':1,'stops_per_day':3}
        raw=plan(PlanRequest.model_validate(request),lambda *_:None,provider=ReportInputProvider()).model_dump(mode='json')
        result=summarize(raw,request)
        self.assertEqual(result['grouping_reason'],'not_applicable')
        self.assertIsNone(result['route_queries'])
        self.assertEqual(result['route_query_upper_bound'],6)
        self.assertEqual(result['totals']['travel_minutes'],74)

    def test_maximum_12_stops_uses_existing_matrix_bound_and_reports_missing_fields(self):
        request={**self.request,'days':3,'stops_per_day':4}
        raw=plan(PlanRequest.model_validate(request),lambda *_:None,provider=ReportInputProvider(12)).model_dump(mode='json')
        result=summarize(raw,request)
        self.assertEqual(len(result['poi_evidence']),12)
        self.assertLessEqual(result['route_queries'],48)
        self.assertEqual(result['missing_fields']['rating'],12)
        self.assertEqual(result['route_query_upper_bound'],48)

    def test_missing_source_timestamps_cannot_be_filled_by_schema_defaults(self):
        for kind in ('poi','route'):
            with self.subTest(kind=kind):
                raw=deepcopy(self.raw)
                source=raw['days'][0]['stops'][0]['poi' if kind=='poi' else 'travel_to_next']['source']
                source.pop('retrieved_at')
                with self.assertRaisesRegex(ValueError,'timestamp_missing'):
                    summarize(raw,self.request)

    def test_keyword_and_reported_city_flags_do_not_fabricate_semantic_scores(self):
        raw=deepcopy(self.raw)
        first=raw['days'][0]['stops'][0]['poi']
        first['name']='TEST ONLY 公园';first['category']='TEST ONLY 公园分类';first['city']='TEST ONLY 其他城市'
        first['missing_fields']=[field for field in first['missing_fields'] if field not in {'category','city'}]
        # This sample's original query is TEST ONLY 公园, so only the first name matches.
        result=summarize(raw,self.request)
        self.assertEqual(result['keyword_evidence']['matched'],1)
        self.assertEqual(len(result['keyword_evidence']['unmatched_ids']),3)
        self.assertEqual(result['different_reported_city_ids'],[first['id']])
        self.assertEqual(len(result['missing_reported_city_ids']),3)
        self.assertTrue(result['review_required'])
        self.assertNotIn('score',result['keyword_evidence'])

    def test_budget_profiles_and_preflight_reject_paid_runs_without_launching_services(self):
        self.assertEqual(sum(case['maximum_provider_calls'] for case in scenarios('smoke','2026-10-22'))*2,52)
        self.assertEqual(sum(case['maximum_provider_calls'] for case in scenarios('expanded','2026-10-22'))*2,138)
        self.assertEqual(provider_call_bound({'days':3,'stops_per_day':1}),1)
        for flags in (['--profile','expanded','--max-provider-calls','100','--live-amap'], []):
            with self.subTest(flags=flags),patch.object(sys,'argv',['verify_live_quality.py','--date','2026-10-22',*flags]),patch('verify_live_quality.subprocess.Popen') as start,patch('verify_live_quality.dotenv_values') as credentials,patch('sys.stderr'):
                with self.assertRaises(SystemExit) as caught:main()
                self.assertEqual(caught.exception.code,2)
                start.assert_not_called();credentials.assert_not_called()

    def test_dry_run_reads_no_credentials_and_starts_no_services(self):
        for profile in ('expanded', 'diverse'):
            with self.subTest(profile=profile),patch.object(sys,'argv',['verify_live_quality.py','--date','2026-10-22','--profile',profile,'--dry-run']),patch('verify_live_quality.subprocess.Popen') as start,patch('verify_live_quality.dotenv_values') as credentials,patch('builtins.print'):
                self.assertEqual(main(),0)
                start.assert_not_called();credentials.assert_not_called()

    def test_report_preserves_task_failure_unknown_status_and_inspector_rejection(self):
        report={'expected_cases':4,'services_stopped_gracefully':True,'cases':[
            {'transport':'direct','status':'succeeded','passed':True},
            {'transport':'direct','status':'failed','passed':False,'error_code':'time_constraint_exceeded'},
            {'transport':'direct','status':'succeeded','passed':False,'error_code':'quality_rejected'},
            {'transport':'direct','passed':False,'error_code':'HTTPError'}]}
        result=finalize_report(report)
        self.assertEqual(result['planning_success_count'],2)
        self.assertEqual(result['planning_failure_count'],1)
        self.assertEqual(result['planning_unknown_count'],1)
        self.assertEqual(result['integrity_rejection_count'],1)
        self.assertFalse(result['passed'])

    def test_transport_comparison_exposes_differences_without_claiming_identical_live_data(self):
        sample={'scenario':'TEST ONLY','status':'succeeded','passed':True,'days':[{'poi_ids':['TEST ONLY a']}],'totals':{'travel_minutes':10}}
        result=finalize_report({'expected_cases':2,'services_stopped_gracefully':True,'cases':[
            {**sample,'transport':'direct'},{**sample,'transport':'mcp','totals':{'travel_minutes':11}}]})
        self.assertTrue(result['passed'])
        self.assertTrue(result['transport_comparisons'][0]['same_ordered_poi_ids'])
        self.assertFalse(result['transport_comparisons'][0]['same_route_totals'])


if __name__ == '__main__':
    unittest.main()
