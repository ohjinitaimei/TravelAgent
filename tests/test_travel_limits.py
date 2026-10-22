"""TEST ONLY factual routes and isolated tasks; never production fallback data."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from pydantic import ValidationError
from test_travel import PAYLOAD, FixtureProvider
from test_journey_endpoints import EndpointProvider, REQUEST, api, result
from test_day_grouping import GeographicFixture, REQUEST as GROUP_REQUEST
from travel.planner import plan
from travel.schemas import PlanRequest, EditRequest, Itinerary
from travel.provider import TravelFailure


class TravelLimitTests(unittest.TestCase):
    def manual(self, values=None, provider=None):
        return plan(PlanRequest.model_validate({**REQUEST, **(values or {})}),lambda *_:None,
                    provider=provider or EndpointProvider(),poi_ids_by_day=[['fixture-a','fixture-b']],optimize_order=False)

    def failure(self, values):
        with self.assertRaises(TravelFailure) as caught:self.manual(values)
        return caught.exception

    def test_unset_limits_report_burden_without_rejecting_or_querying_extra_routes(self):
        provider=EndpointProvider()
        trip=self.manual({'stay_minutes':10},provider)
        day=trip.travel_load.days[0]
        self.assertEqual((day.stay_minutes,day.travel_minutes,day.longest_leg_minutes),(20,46,23))
        self.assertEqual(day.travel_share_of_scheduled,.697)
        self.assertTrue(day.travel_at_least_stay)
        self.assertEqual(len(provider.routes),3)
        self.assertIsNone(trip.budget.total)

    def test_equality_to_both_explicit_limits_is_accepted(self):
        trip=self.manual({'max_leg_travel_minutes':23,'max_daily_travel_minutes':46})
        self.assertEqual(trip.travel_load.max_leg_travel_minutes,23)
        self.assertEqual(trip.travel_load.days[0].violating_legs,[])

    def test_return_leg_exceedance_is_not_hidden_by_a_feasible_day_window(self):
        error=self.failure({'max_leg_travel_minutes':22})
        self.assertEqual(error.code,'travel_constraint_exceeded')
        self.assertFalse(error.retryable)
        self.assertIsNone(error.time_constraints)
        details=error.travel_constraints
        self.assertEqual(details.operation,'plan')
        leg=details.days[0].violating_legs[0]
        self.assertEqual((leg.kind,leg.origin_id,leg.destination_id,leg.duration_min,leg.overrun_minutes),('destination','fixture-b','hotel',23,1))

    def test_daily_limit_includes_incoming_and_return(self):
        error=self.failure({'max_daily_travel_minutes':45})
        day=error.travel_constraints.days[0]
        self.assertEqual((day.travel_minutes,day.over_daily_minutes),(46,1))
        self.assertEqual(day.violating_legs,[])

    def test_limits_apply_to_current_driving_mode_without_automatic_mode_change(self):
        self.assertEqual(self.manual({'mode':'driving','max_daily_travel_minutes':46}).travel_load.mode,'driving')
        self.assertEqual(self.failure({'mode':'driving','max_leg_travel_minutes':22}).travel_constraints.mode,'driving')

    def test_time_failure_retains_original_diagnostics_when_both_constraints_fail(self):
        error=self.failure({'day_end':'11:00','max_leg_travel_minutes':1})
        self.assertEqual(error.code,'time_constraint_exceeded')
        self.assertEqual(error.time_constraints.days[0].required_minutes,166)
        self.assertIsNone(error.travel_constraints)

    def test_existing_bounded_candidates_can_resolve_explicit_travel_limits(self):
        provider=GeographicFixture()
        trip=plan(PlanRequest(**{**GROUP_REQUEST,'max_leg_travel_minutes':20,'max_daily_travel_minutes':50}),lambda *_:None,provider=provider)
        self.assertTrue(trip.optimization.applied)
        self.assertFalse(trip.optimization.baseline.feasible)
        self.assertEqual(trip.optimization.reason,'feasible_candidate')
        self.assertTrue(all(day.longest_leg_minutes==10 for day in trip.travel_load.days))
        self.assertEqual(len(provider.calls),len(set(provider.calls)))
        self.assertLessEqual(len(provider.calls),12)

    def test_unacceptable_candidates_fail_instead_of_relaxing_the_limit(self):
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest(**{**GROUP_REQUEST,'max_leg_travel_minutes':1}),lambda *_:None,provider=GeographicFixture())
        error=caught.exception
        self.assertEqual(error.code,'travel_constraint_exceeded')
        self.assertEqual([day.day_number for day in error.travel_constraints.days],[1,2])
        self.assertEqual(error.travel_constraints.max_leg_travel_minutes,1)
        self.assertEqual(error.travel_constraints.basis,'original_partition')

    def test_no_route_is_reported_as_absent_instead_of_a_fake_zero_minute_leg(self):
        trip=plan(PlanRequest.model_validate({**PAYLOAD,'stops_per_day':1,'max_leg_travel_minutes':1,'max_daily_travel_minutes':1}),
                  lambda *_:None,provider=FixtureProvider())
        day=trip.travel_load.days[0]
        self.assertIsNone(day.longest_leg_minutes)
        self.assertEqual(day.travel_minutes,0)
        self.assertFalse(day.travel_at_least_stay)

    def test_invalid_or_coerced_limits_are_rejected_and_null_clears_edits(self):
        for field in ('max_leg_travel_minutes','max_daily_travel_minutes'):
            for value in (0,1440,1.5,'30',True):
                with self.subTest(field=field,value=value),self.assertRaises(ValidationError):PlanRequest.model_validate({**PAYLOAD,field:value})
            self.assertIn(field,EditRequest.model_validate({'poi_ids_by_day':[['a']],field:None}).model_fields_set)

    def test_legacy_saved_record_remains_without_a_manufactured_load_report(self):
        raw=self.manual().model_dump(mode='json')
        raw.pop('travel_load')
        for field in ('max_leg_travel_minutes','max_daily_travel_minutes'):raw['request'].pop(field)
        old=Itinerary.from_saved_json(json.dumps(raw))
        self.assertIsNone(old.travel_load)
        self.assertIsNone(old.request.max_daily_travel_minutes)


class TravelLimitApiTests(unittest.TestCase):
    def test_failed_adjustment_persists_diagnostics_and_preserves_source_then_null_clears(self):
        with api() as (client,_):
            parent=result(client,client.post('/api/v1/travel/tasks',json={**PAYLOAD,'max_leg_travel_minutes':40,'max_daily_travel_minutes':75}))
            path='/api/v1/travel/itineraries/'+parent['id']+'/adjust'
            groups=[[s['poi']['id'] for s in day['stops']] for day in parent['days']]
            preserved=result(client,client.post(path,json={'poi_ids_by_day':groups}))
            self.assertEqual(preserved['request']['max_leg_travel_minutes'],40)
            response=client.post(path,json={'poi_ids_by_day':groups,'max_leg_travel_minutes':36})
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                failed=client.get('/api/v1/travel/tasks/'+response.json()['id']).json()
                if failed['status'] not in {'queued','running'}:break
                time.sleep(.05)
            else:self.fail('TEST ONLY task deadline')
            self.assertEqual(failed['error']['code'],'travel_constraint_exceeded')
            self.assertEqual(failed['error']['travel_constraints']['source_itinerary_id'],parent['id'])
            self.assertFalse(failed['retry_available'])
            self.assertIsNone(failed['itinerary_id'])
            self.assertEqual(client.get(path.removesuffix('/adjust')).json(),parent)
            cleared=result(client,client.post(path,json={'poi_ids_by_day':groups,'max_leg_travel_minutes':None,'max_daily_travel_minutes':None}))
            self.assertIsNone(cleared['request']['max_leg_travel_minutes'])
            self.assertIsNone(cleared['travel_load']['max_daily_travel_minutes'])

if __name__=='__main__':unittest.main()
