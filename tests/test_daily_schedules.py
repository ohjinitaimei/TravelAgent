"""TEST ONLY user schedules and factual matrices; never production fallback."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'scripts'))
from pydantic import ValidationError
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import PlanRequest, EditRequest, Itinerary
from travel.planning_budget import planning_budget
from test_travel import PAYLOAD
from test_journey_endpoints import EndpointProvider, api, result
from test_day_grouping import GeographicFixture, REQUEST as GEO
from test_live_quality import ReportInputProvider
from verify_live_quality import summarize

SCHEDULES=[{'day_start':'08:00','day_end':'12:00','stay_minutes':30},
           {'day_start':'14:00','day_end':'18:00','stay_minutes':45}]
REQUEST={**PAYLOAD,'days':2,'day_schedules':SCHEDULES}
GROUPS=[['fixture-a','fixture-b'],['fixture-c','fixture-d']]

class DailyScheduleTests(unittest.TestCase):
    def test_daily_window_default_and_stop_override_use_existing_scheduler(self):
        provider=EndpointProvider()
        request={**REQUEST,'stay_minutes_by_poi':{'fixture-c':20}}
        trip=plan(PlanRequest.model_validate(request),lambda *_:None,provider=provider,poi_ids_by_day=GROUPS,optimize_order=False)
        self.assertEqual([[s.stay_minutes for s in d.stops] for d in trip.days],[[30,30],[20,45]])
        self.assertEqual([[s.arrival_time for s in d.stops] for d in trip.days],[['08:00','08:43'],['14:00','14:39']])
        self.assertEqual([d.schedule.model_dump() for d in trip.days],SCHEDULES)
        self.assertEqual(provider.routes,[('fixture-a','fixture-b'),('fixture-c','fixture-d')])
        self.assertIsNone(trip.budget.total)

    def test_daily_boundaries_and_travel_limits_keep_actual_period(self):
        request={**REQUEST,'day_endpoints':[{'origin_poi_id':'home','destination_poi_id':'hotel'},{}],'max_daily_travel_minutes':50}
        trip=plan(PlanRequest.model_validate(request),lambda *_:None,provider=EndpointProvider(),poi_ids_by_day=GROUPS,optimize_order=False)
        self.assertEqual(trip.days[0].origin_departure_time,'08:00')
        self.assertEqual(trip.days[0].return_arrival_time,'09:46')
        self.assertEqual(trip.days[1].stops[0].arrival_time,'14:00')
        self.assertEqual([d.travel_minutes for d in trip.travel_load.days],[46,19])

    def test_only_affected_day_reports_its_own_window_without_extra_calls(self):
        daily=[SCHEDULES[0],{**SCHEDULES[1],'day_end':'15:30'}]
        provider=EndpointProvider()
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate({**REQUEST,'day_schedules':daily}),lambda *_:None,provider=provider,poi_ids_by_day=GROUPS,optimize_order=False,parent_id='TEST ONLY source')
        error=caught.exception
        self.assertEqual(error.code,'time_constraint_exceeded');self.assertFalse(error.retryable)
        details=error.time_constraints
        self.assertEqual(details.operation,'adjust');self.assertEqual(details.source_itinerary_id,'TEST ONLY source')
        self.assertEqual(details.available_minutes,540) # legacy shared header remains compatible
        self.assertEqual([d.day_number for d in details.days],[2])
        d=details.days[0]
        self.assertEqual((d.day_start,d.day_end,d.available_minutes,d.stay_minutes,d.required_minutes,d.overrun_minutes),('14:00','15:30',90,90,109,19))
        self.assertEqual(len(provider.routes),2)

    def test_regrouping_recomputes_destination_day_stays_and_feasibility(self):
        daily=[{'day_start':'08:00','day_end':'09:30','stay_minutes':20},
               {'day_start':'13:00','day_end':'15:30','stay_minutes':60}]
        provider=GeographicFixture()
        trip=plan(PlanRequest.model_validate({**GEO,'day_schedules':daily,'stay_minutes_by_poi':{'test-02':30}}),lambda *_:None,provider=provider)
        self.assertTrue(trip.optimization.applied);self.assertFalse(trip.optimization.baseline.feasible)
        self.assertTrue(trip.optimization.result.feasible)
        moved=False
        for i,day in enumerate(trip.days):
            for stop in day.stops:
                self.assertEqual(stop.stay_minutes,30 if stop.poi.id=='test-02' else daily[i]['stay_minutes'])
                moved |= stop.poi.id not in trip.optimization.baseline_poi_ids_by_day[i]
        self.assertTrue(moved);self.assertLessEqual(len(provider.calls),12)

    def test_schema_rejects_incomplete_coerced_count_and_fact_inputs(self):
        invalid=[[],[SCHEDULES[0]],SCHEDULES+[SCHEDULES[0]],
            [{**SCHEDULES[0],'day_end':'08:00'},SCHEDULES[1]],
            [{**SCHEDULES[0],'day_start':'23:00'},SCHEDULES[1]],
            [{**SCHEDULES[0],'day_start':'8:00'},SCHEDULES[1]],
            [{'day_start':'08:00','day_end':'12:00'},SCHEDULES[1]],
            [{**SCHEDULES[0],'source':'amap'},SCHEDULES[1]]]
        invalid += [[{**SCHEDULES[0],'stay_minutes':v},SCHEDULES[1]] for v in ('30',True,30.5,9,361,None)]
        for daily in invalid:
            with self.subTest(daily=daily),self.assertRaises(ValidationError):PlanRequest.model_validate({**REQUEST,'day_schedules':daily})
        with self.assertRaises(ValidationError):EditRequest.model_validate({'poi_ids_by_day':GROUPS,'day_schedules':[SCHEDULES[0]]})

    def test_legacy_shared_request_saved_schedule_and_null_remain_readable(self):
        raw=plan(PlanRequest.model_validate(PAYLOAD),lambda *_:None,provider=EndpointProvider()).model_dump(mode='json')
        raw['request'].pop('day_schedules');raw['days'][0].pop('schedule')
        old=Itinerary.model_validate(raw)
        self.assertIsNone(old.request.day_schedules);self.assertIsNone(old.days[0].schedule)
        null=plan(PlanRequest.model_validate({**PAYLOAD,'day_schedules':None}),lambda *_:None,provider=EndpointProvider())
        self.assertEqual(null.days[0].schedule.stay_minutes,60)

    def test_api_omit_preserves_null_clears_and_changed_defaults_respect_stop_override(self):
        with api() as (client,_):
            parent=result(client,client.post('/api/v1/travel/tasks',json={**REQUEST,'stops_per_day':1}))
            path='/api/v1/travel/itineraries/'+parent['id']
            groups=[[day['stops'][0]['poi']['id']] for day in parent['days']]
            edit={'poi_ids_by_day':groups}
            keep=result(client,client.post(path+'/adjust',json=edit))
            self.assertEqual(keep['request']['day_schedules'],SCHEDULES)
            changed=[SCHEDULES[0],{**SCHEDULES[1],'stay_minutes':70}]
            child=result(client,client.post(path+'/adjust',json={**edit,'day_schedules':changed,'stay_minutes_by_poi':{groups[1][0]:25}}))
            self.assertEqual(child['days'][1]['schedule']['stay_minutes'],70)
            self.assertEqual(child['days'][1]['stops'][0]['stay_minutes'],25)
            cleared=result(client,client.post(path+'/adjust',json={**edit,'day_schedules':None}))
            self.assertEqual([d['stops'][0]['arrival_time'] for d in cleared['days']],['09:00','09:00'])
            self.assertEqual([d['stops'][0]['stay_minutes'] for d in cleared['days']],[60,60])
            self.assertEqual(client.get(path).json(),parent)

    def test_api_invalid_merge_rejects_before_enqueue_and_daily_order_matters(self):
        with api() as (client,app):
            parent=result(client,client.post('/api/v1/travel/tasks',json={**REQUEST,'stops_per_day':1},headers={'Idempotency-Key':'test-only-schedules'}))
            conflict=client.post('/api/v1/travel/tasks',json={**REQUEST,'stops_per_day':1,'day_schedules':list(reversed(SCHEDULES))},headers={'Idempotency-Key':'test-only-schedules'})
            self.assertEqual(conflict.status_code,409)
            with patch.object(app.state.travel,'create') as create:
                response=client.post('/api/v1/travel/itineraries/'+parent['id']+'/adjust',json={'poi_ids_by_day':[['fixture-a']]})
                self.assertEqual(response.status_code,422);create.assert_not_called()

    def test_quality_gate_checks_resolved_schedule_override_and_daily_available_minutes(self):
        request={**REQUEST,'stops_per_day':1,'stay_minutes_by_poi':{'fixture-a':25}}
        raw=plan(PlanRequest.model_validate(request),lambda *_:None,provider=ReportInputProvider(2)).model_dump(mode='json')
        report=summarize(raw,request)
        self.assertEqual([d['remaining_minutes'] for d in report['quality_observations']['days']],[215,195])
        for change in ('schedule','arrival','duration'):
            bad=deepcopy(raw)
            if change=='schedule':bad['days'][1]['schedule']['day_start']='09:00'
            if change=='arrival':bad['days'][1]['stops'][0]['arrival_time']='09:00'
            if change=='duration':bad['days'][1]['stops'][0]['stay_minutes']=60
            with self.subTest(change=change),self.assertRaises(ValueError):summarize(bad,request)

    def test_schedules_do_not_expand_provider_budget(self):
        for editing in (False,True):
            plain=PlanRequest.model_validate({**PAYLOAD,'days':2})
            custom=PlanRequest.model_validate(REQUEST)
            groups=GROUPS if editing else None
            self.assertEqual(planning_budget(plain,groups,False),planning_budget(custom,groups,False))

if __name__=='__main__':unittest.main()
