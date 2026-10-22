"""TEST ONLY per-day selections and matrices, never production fallback data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'scripts'))
from pydantic import ValidationError
from travel.planner import plan
from travel.planning_budget import planning_budget
from travel.provider import TravelFailure
from travel.schemas import PlanRequest, EditRequest, Itinerary, Task
from test_travel import PAYLOAD
from test_journey_endpoints import EndpointProvider, LargeEndpointProvider, api, result

DAILY=[{'origin_poi_id':'home','destination_poi_id':'hotel'},
       {'origin_poi_id':'other-home','destination_poi_id':'other-hotel'}]
REQUEST={**PAYLOAD,'days':2,'day_endpoints':DAILY}
GROUPS=[['fixture-a','fixture-b'],['fixture-c','fixture-d']]


class DailyEndpointTests(unittest.TestCase):
    def test_distinct_days_reuse_scheduler_and_never_infer_overnight_transfer(self):
        provider=EndpointProvider()
        trip=plan(PlanRequest.model_validate(REQUEST),lambda *_:None,provider=provider,poi_ids_by_day=GROUPS,optimize_order=False)
        self.assertEqual([d.stops[0].arrival_time for d in trip.days],['09:10','09:19'])
        self.assertEqual([d.return_arrival_time for d in trip.days],['11:46','11:57'])
        self.assertEqual([d.origin_departure_time for d in trip.days],['09:00','09:00'])
        self.assertEqual(trip.travel_load.days[1].travel_minutes,57)
        self.assertNotIn(('hotel','other-home'),provider.routes)
        self.assertIsNone(trip.budget.total)

    def test_null_side_clears_one_day_and_repeated_ids_are_looked_up_once(self):
        provider=EndpointProvider()
        request={**REQUEST,'day_endpoints':[DAILY[0],{'origin_poi_id':'home','destination_poi_id':None}]}
        trip=plan(PlanRequest.model_validate(request),lambda *_:None,provider=provider,poi_ids_by_day=GROUPS,optimize_order=False)
        self.assertEqual(provider.details.count('home'),1)
        self.assertEqual(provider.details.count('hotel'),1)
        self.assertIsNone(trip.days[1].destination_poi)
        self.assertIsNone(trip.days[1].return_arrival_time)
        self.assertEqual(trip.days[0].destination_poi.id,'hotel')

    def test_same_visit_as_daily_boundary_does_not_create_zero_fact(self):
        provider=EndpointProvider()
        request={**REQUEST,'stops_per_day':1,'day_endpoints':[{'origin_poi_id':'fixture-a','destination_poi_id':'fixture-a'},{}]}
        trip=plan(PlanRequest.model_validate(request),lambda *_:None,provider=provider,poi_ids_by_day=[['fixture-a'],['fixture-b']],optimize_order=False)
        self.assertEqual(provider.routes,[])
        self.assertEqual(provider.details,['fixture-a','fixture-b'])
        self.assertIsNone(trip.days[0].origin_segment)
        self.assertEqual(trip.days[0].return_arrival_time,'10:00')
        self.assertEqual(trip.days[1].stops[0].arrival_time,'09:00')

    def test_travel_and_time_diagnostics_identify_only_the_affected_day(self):
        for field,value,code in [('day_end','11:50','time_constraint_exceeded'),('max_daily_travel_minutes',50,'travel_constraint_exceeded')]:
            with self.subTest(field=field),self.assertRaises(TravelFailure) as caught:
                plan(PlanRequest.model_validate({**REQUEST,field:value}),lambda *_:None,provider=EndpointProvider(),poi_ids_by_day=GROUPS,optimize_order=False)
            error=caught.exception;self.assertEqual(error.code,code)
            details=error.time_constraints or error.travel_constraints
            self.assertEqual([day.day_number for day in details.days],[2])

    def test_cross_day_candidates_reserve_new_daily_anchor_routes_before_querying(self):
        daily=[{'origin_poi_id':f'home-{i}','destination_poi_id':f'hotel-{i}'} for i in range(3)]
        request=PlanRequest.model_validate({**PAYLOAD,'days':3,'stops_per_day':3,'stay_minutes':10,'day_endpoints':daily})
        provider=LargeEndpointProvider()
        def rotations(groups,**kwargs):return [groups[1:]+groups[:1],groups[2:]+groups[:2]]
        with patch('services.route_planner.propose_day_group_candidates',rotations):
            trip=plan(request,lambda *_:None,provider=provider)
        self.assertEqual(len(trip.optimization.candidates),1)
        self.assertTrue(trip.optimization.candidate_search_limited)
        self.assertEqual(len(provider.routes),54)
        self.assertEqual(provider.searches+len(provider.details)+len(provider.routes),61)
        self.assertEqual(len(provider.routes),len(set(provider.routes)))

    def test_unaffordable_baseline_is_rejected_before_any_provider_call(self):
        request=PlanRequest.model_validate({**PAYLOAD,'days':3,'stops_per_day':4,
            'day_endpoints':[{'origin_poi_id':f'home-{i}','destination_poi_id':f'hotel-{i}'} for i in range(3)]})
        provider=LargeEndpointProvider()
        with self.assertRaises(TravelFailure) as caught:plan(request,lambda *_:None,provider=provider)
        self.assertEqual(caught.exception.code,'planning_budget_exceeded')
        self.assertEqual((provider.searches,provider.details,provider.routes),(0,[],[]))
        groups=[[f'fixture-{i}' for i in range(d*4,(d+1)*4)] for d in range(3)]
        self.assertEqual(planning_budget(request,groups,False).total_calls,33)

    def test_schema_rejects_mixed_counts_blank_ids_and_non_user_fields(self):
        invalid=[{'day_endpoints':[]},{'day_endpoints':[{}]},
            {'day_endpoints':[{}, {}, {}]}, {'day_origin_poi_id':'home'},
            {'day_endpoints':[{'origin_poi_id':' '},{}]},
            {'day_endpoints':[{'destination_poi_id':1},{}]},
            {'day_endpoints':[{'latitude':10},{}]}]
        for change in invalid:
            with self.subTest(change=change),self.assertRaises(ValidationError):PlanRequest.model_validate({**REQUEST,**change})
        with self.assertRaises(ValidationError):EditRequest.model_validate({'poi_ids_by_day':GROUPS,'day_endpoints':[{}]})

    def test_legacy_requests_and_saved_records_default_to_shared_mode(self):
        raw=plan(PlanRequest.model_validate(PAYLOAD),lambda *_:None,provider=EndpointProvider()).model_dump(mode='json')
        raw['request'].pop('day_endpoints')
        self.assertIsNone(Itinerary.model_validate(raw).request.day_endpoints)
        self.assertIsNone(PlanRequest.model_validate({**PAYLOAD,'day_endpoints':None}).day_endpoints)

    def test_api_adjust_omit_clear_and_mode_switch_preserve_source(self):
        with api() as (client,_):
            request={**REQUEST,'stops_per_day':1}
            parent=result(client,client.post('/api/v1/travel/tasks',json=request))
            path='/api/v1/travel/itineraries/'+parent['id']+'/adjust'
            edit={'poi_ids_by_day':[[day['stops'][0]['poi']['id']] for day in parent['days']]}
            preserved=result(client,client.post(path,json=edit))
            self.assertEqual(preserved['request']['day_endpoints'],DAILY)
            changed=[deepcopy(DAILY[0]),{**DAILY[1],'destination_poi_id':None}]
            child=result(client,client.post(path,json={**edit,'day_endpoints':changed}))
            self.assertIsNone(child['days'][1]['destination_poi'])
            self.assertEqual(child['days'][0]['destination_poi']['id'],'hotel')
            shared=result(client,client.post(path,json={**edit,'day_endpoints':None,'day_origin_poi_id':'home'}))
            self.assertTrue(all(day['origin_poi']['id']=='home' for day in shared['days']))
            self.assertTrue(all(day['destination_poi'] is None for day in shared['days']))
            self.assertEqual(client.get(path.removesuffix('/adjust')).json(),parent)

    def test_invalid_api_merge_is_rejected_before_enqueue_and_receipt_keeps_array_order(self):
        with api() as (client,app):
            parent=result(client,client.post('/api/v1/travel/tasks',json={**REQUEST,'stops_per_day':1},headers={'Idempotency-Key':'test-only-daily'}))
            response=client.post('/api/v1/travel/tasks',json={**REQUEST,'stops_per_day':1,'day_endpoints':list(reversed(DAILY))},headers={'Idempotency-Key':'test-only-daily'})
            self.assertEqual(response.status_code,409)
            path='/api/v1/travel/itineraries/'+parent['id']+'/adjust'
            with patch.object(app.state.travel,'create') as create:
                bad=client.post(path,json={'poi_ids_by_day':[['fixture-a'],['fixture-b']],'day_origin_poi_id':'home'})
                self.assertEqual(bad.status_code,422);create.assert_not_called()

    def test_pre_extension_receipt_accepts_null_without_fingerprint_conflict(self):
        with api() as (client,app):
            request=PlanRequest.model_validate(PAYLOAD).model_dump(mode='json')
            for field in ('day_origin_poi_id','day_destination_poi_id','day_endpoints','max_leg_travel_minutes','max_daily_travel_minutes'):request.pop(field)
            payload={'request':request}
            fingerprint=hashlib.sha256(json.dumps({'payload':payload,'retry_of':None},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            app.state.travel.store.register_task(Task(id='TEST ONLY old',status='failed'),payload,'test-only-legacy-daily',fingerprint)
            response=client.post('/api/v1/travel/tasks',json={**PAYLOAD,'day_endpoints':None},headers={'Idempotency-Key':'test-only-legacy-daily'})
            self.assertEqual(response.status_code,202,response.text);self.assertEqual(response.json()['id'],'TEST ONLY old')

    def test_real_quality_inspector_validates_each_selected_day_and_rejects_swapped_facts(self):
        from test_live_quality import ReportInputProvider
        from verify_live_quality import summarize
        request={**REQUEST,'stay_minutes':10}
        raw=plan(PlanRequest.model_validate(request),lambda *_:None,provider=ReportInputProvider(4)).model_dump(mode='json')
        self.assertTrue(summarize(raw,request)['quality_observations']['origin_return_included'])
        bad=deepcopy(raw);bad['days'][1]['origin_poi']=deepcopy(bad['days'][0]['origin_poi'])
        with self.assertRaises(ValueError):summarize(bad,request)


if __name__=='__main__':unittest.main()
