"""TEST ONLY measured roads; no production fixture or synthetic fallback."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'scripts'))
from pydantic import ValidationError
from travel.schemas import PlanRequest, Itinerary, Source, Poi, Point, Segment
from travel.planner import plan
from travel.planning_budget import planning_budget
from travel.provider import TravelFailure
from services import route_planner,poi_ranker
from verify_live_quality import summarize, scenarios, provider_call_bound
from test_journey_endpoints import api,result,LargeEndpointProvider

REQUEST={'city':'TEST ONLY','query':'公园','start_date':'2026-10-23','days':1,'stops_per_day':2,'stay_minutes':30,'compare_poi_alternatives':True}
class AlternativeProvider:
    def __init__(self,detour=False,fail=False):
        self.routes=[];self.details=[];self.searches=0;self.detour=detour;self.fail=fail
    def poi(self,identifier):
        lng={'a':120.,'b':121.,'c':120.01,'d':120.02,'home':120.,'hotel':120.}.get(identifier,120.)
        return Poi(id=identifier,name='TEST ONLY 公园 '+identifier,longitude=lng,latitude=30,
            source=Source(provider='user_input'),missing_fields=['city','address','category','rating','average_spend','opening_hours'])
    def search(self,*_):
        self.searches+=1;return [self.poi(x) for x in 'abcd']
    def detail(self,identifier):self.details.append(identifier);return self.poi(identifier)
    def route(self,a,b,mode):
        self.routes.append((a.id,b.id))
        if self.fail and any(abs(p.longitude-120.01)<1e-6 for p in (a,b)):raise TravelFailure('provider_timeout','TEST ONLY real-road outage',True,504)
        minutes=100 if any(abs(p.longitude-121)<1e-6 for p in (a,b)) else 10
        if self.detour and any(abs(p.longitude-120.01)<1e-6 for p in (a,b)):minutes=150
        return Segment(origin_id=a.id,destination_id=b.id,mode=mode,distance_km=minutes/10,duration_min=minutes,
            source=Source(provider='user_input'),polyline=[Point(longitude=a.longitude,latitude=a.latitude),Point(longitude=b.longitude,latitude=b.latitude)])
class RatingAlternativeProvider(AlternativeProvider):
    def poi(self,identifier):
        p=super().poi(identifier);p.rating={'a':5,'b':4.8,'c':4.7,'d':4.6}.get(identifier)
        if p.rating is not None:p.missing_fields.remove('rating')
        return p

def alternative_worker(payload,output):
    from travel.worker import run
    def injected(request,emit,**options):
        options.pop('gateway',None)
        return plan(request,emit,provider=RatingAlternativeProvider() if request.budget==123.45 else AlternativeProvider(),**options)
    with patch('travel.worker.plan',injected):return run(payload,output)

class ReportAlternativeProvider(AlternativeProvider):
    def poi(self,identifier):
        p=super().poi(identifier);p.source=Source(provider='amap');return p
    def route(self,*args):
        leg=super().route(*args);leg.source=Source(provider='amap');return leg

class PoiComparisonTests(unittest.TestCase):
    def test_single_day_replaces_unselected_real_poi_and_proves_shared_fact_gain(self):
        provider=AlternativeProvider()
        with patch.object(route_planner,'_simple_estimate_distance',side_effect=AssertionError('No estimated traffic')),patch.object(route_planner,'_build_route_stops',wraps=route_planner._build_route_stops) as scheduler:
            trip=plan(PlanRequest(**REQUEST),lambda *_:None,provider=provider)
        q=trip.planning_comparison
        self.assertTrue(q.applied);self.assertEqual(q.reason,'improved')
        self.assertEqual([s.poi.id for s in trip.days[0].stops],['a','c'])
        self.assertEqual([s.poi.id for s in q.baseline_days[0].stops],['a','b'])
        self.assertEqual((q.baseline.travel_minutes,q.result.travel_minutes),(100,10))
        self.assertEqual((q.baseline.longest_leg_minutes,q.result.longest_leg_minutes),(100,10))
        self.assertEqual(scheduler.call_count,1+len(q.candidates))
        self.assertEqual(provider.searches,1);self.assertEqual(provider.details,[])
        self.assertEqual(q.provider_calls,1+len(provider.routes));self.assertLessEqual(q.provider_calls,q.provider_call_upper_bound)
        self.assertEqual(len(provider.routes),len(set(provider.routes)));self.assertIsNone(trip.optimization)

    def test_geographic_near_but_bad_roads_are_not_adopted(self):
        trip=plan(PlanRequest(**REQUEST),lambda *_:None,provider=AlternativeProvider(detour=True))
        q=trip.planning_comparison
        self.assertTrue(q.applied)
        self.assertNotIn('c',[s.poi.id for s in trip.days[0].stops])
        self.assertTrue(any(c.metrics.travel_minutes>q.baseline.travel_minutes for c in q.candidates))

    def test_user_cost_and_duration_bindings_protect_selected_poi(self):
        for change in ({'user_prices':{'b':0}},{'stay_minutes_by_poi':{'b':90}}):
            with self.subTest(change=change):
                trip=plan(PlanRequest(**{**REQUEST,**change}),lambda *_:None,provider=AlternativeProvider())
                self.assertFalse(trip.planning_comparison.applied)
                self.assertIn('b',[s.poi.id for s in trip.days[0].stops])
                self.assertTrue(all('b' in c.poi_ids_by_day[0] for c in trip.planning_comparison.candidates))

    def test_failed_required_candidate_facts_fail_without_partial_trip(self):
        with self.assertRaises(TravelFailure) as caught:plan(PlanRequest(**REQUEST),lambda *_:None,provider=AlternativeProvider(fail=True))
        self.assertEqual(caught.exception.code,'provider_timeout')

    def test_infeasible_baseline_can_be_rescued_without_relaxing_period_or_stay(self):
        trip=plan(PlanRequest(**{**REQUEST,'day_end':'10:20'}),lambda *_:None,provider=AlternativeProvider())
        q=trip.planning_comparison
        self.assertFalse(q.baseline.feasible);self.assertTrue(q.result.feasible);self.assertEqual(q.reason,'feasible_candidate')
        self.assertEqual([s.stay_minutes for s in trip.days[0].stops],[30,30])
        self.assertEqual(trip.request.day_end,'10:20')

    def test_no_better_candidate_keeps_actual_baseline(self):
        class EqualProvider(AlternativeProvider):
            def route(self,*args):
                p=super().route(*args);p.duration_min=10;p.distance_km=1;return p
        q=plan(PlanRequest(**REQUEST),lambda *_:None,provider=EqualProvider()).planning_comparison
        self.assertFalse(q.applied);self.assertEqual(q.reason,'baseline_preferred');self.assertEqual(q.result,q.baseline)

    def test_single_stop_uses_daily_boundaries_but_no_transport_adds_no_routes(self):
        for anchors in (False,True):
            provider=AlternativeProvider()
            trip=plan(PlanRequest(**{**REQUEST,'days':2,'stops_per_day':1,**({'day_origin_poi_id':'home','day_destination_poi_id':'hotel'} if anchors else {})}),lambda *_:None,provider=provider)
            q=trip.planning_comparison
            if anchors:
                self.assertTrue(q.applied);self.assertLess(q.result.travel_minutes,q.baseline.travel_minutes)
                self.assertEqual(len(provider.details),2)
            else:
                self.assertEqual(q.reason,'no_transport_legs');self.assertEqual(provider.routes,[]);self.assertEqual(q.provider_calls,1)

    def test_manual_edit_never_replaces_or_regroups_even_if_flag_inherited(self):
        provider=AlternativeProvider()
        trip=plan(PlanRequest(**REQUEST),lambda *_:None,provider=provider,poi_ids_by_day=[['a','b']],parent_id='TEST ONLY source',optimize_order=True)
        self.assertEqual({s.poi.id for s in trip.days[0].stops},{'a','b'});self.assertIsNone(trip.planning_comparison)
        self.assertEqual(provider.searches,0)

    def test_relevance_is_protected_but_factual_rating_is_not_an_unrequested_hard_limit(self):
        request=PlanRequest(**REQUEST)
        from travel.planner import legacy
        provider=AlternativeProvider();pois=provider.search()
        entries=[{'poi':legacy(p,request),'score_breakdown':{'query_alignment_score':1 if p.id in 'ab' else 0,'category_match_score':1}} for p in pois]
        proposals=route_planner.propose_travel_candidates([[entries[0]['poi'],entries[1]['poi']]],entries,anchors=[(None,None)])
        self.assertFalse(any(kind=='replacement' for kind,_ in proposals))
        for entry in entries:entry['score_breakdown']['query_alignment_score']=1
        entries[1]['poi'].rating=5;entries[1]['poi'].factual_fields=['rating']
        proposals=route_planner.propose_travel_candidates([[entries[0]['poi'],entries[1]['poi']]],entries,anchors=[(None,None)],protected_ids={'a'})
        self.assertTrue(any(kind=='replacement' for kind,_ in proposals))

    def test_daily_single_stop_assignment_can_swap_selected_pois_without_new_candidates(self):
        class TwoPois(AlternativeProvider):
            def search(self,*_):self.searches+=1;return [self.poi(x) for x in 'ab']
        request={**REQUEST,'days':2,'stops_per_day':1,'day_endpoints':[{'origin_poi_id':'b'},{'origin_poi_id':'a'}]}
        trip=plan(PlanRequest(**request),lambda *_:None,provider=TwoPois())
        self.assertTrue(trip.planning_comparison.applied)
        self.assertEqual(trip.planning_comparison.result_poi_ids_by_day,[['b'],['a']])
        self.assertEqual(trip.planning_comparison.result.travel_minutes,0)
        self.assertTrue(all(d.origin_segment is None for d in trip.days))

    def test_all_infeasible_candidates_emit_no_successful_selection_event(self):
        stages=[]
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest(**{**REQUEST,'day_end':'09:05'}),lambda stage,_:stages.append(stage),provider=AlternativeProvider())
        self.assertEqual(caught.exception.code,'time_constraint_exceeded')
        self.assertNotIn('selection_validated',stages)

    def test_daily_schedules_recompute_defaults_for_adopted_day(self):
        daily=[{'day_start':'08:00','day_end':'18:00','stay_minutes':20},{'day_start':'13:00','day_end':'22:00','stay_minutes':45}]
        trip=plan(PlanRequest(**{**REQUEST,'days':2,'stops_per_day':1,'day_schedules':daily,'day_origin_poi_id':'home'}),lambda *_:None,provider=AlternativeProvider())
        self.assertTrue(trip.planning_comparison.applied)
        self.assertEqual([d.stops[0].stay_minutes for d in trip.days],[20,45])
        self.assertEqual([d.origin_departure_time for d in trip.days],['08:00','13:00'])

    def test_maximum_shape_prunes_before_query_and_never_exceeds_64(self):
        provider=LargeEndpointProvider()
        request=PlanRequest(**{**REQUEST,'days':3,'stops_per_day':4,'stay_minutes':10,'day_origin_poi_id':'home','day_destination_poi_id':'hotel'})
        trip=plan(request,lambda *_:None,provider=provider)
        q=trip.planning_comparison
        self.assertLessEqual(q.provider_calls,64);self.assertLessEqual(q.provider_call_upper_bound,64)
        self.assertEqual(len(provider.routes),len(set(provider.routes)))
        self.assertLessEqual(len(q.candidates),3)

    def test_false_default_old_records_and_strict_flag_remain_compatible(self):
        q=PlanRequest(**{k:v for k,v in REQUEST.items() if k!='compare_poi_alternatives'})
        trip=plan(q,lambda *_:None,provider=AlternativeProvider())
        self.assertIsNone(trip.planning_comparison)
        raw=trip.model_dump(mode='json');raw.pop('planning_comparison');raw['request'].pop('compare_poi_alternatives')
        self.assertFalse(Itinerary.model_validate(raw).request.compare_poi_alternatives)
        for value in ('true',1,None):
            with self.subTest(value=value),self.assertRaises(ValidationError):PlanRequest(**{**REQUEST,'compare_poi_alternatives':value})

    def test_quality_gate_recomputes_baseline_adoption_and_rejects_false_benefits(self):
        request={**REQUEST,'day_end':'10:20'}
        raw=plan(PlanRequest(**request),lambda *_:None,provider=ReportAlternativeProvider()).model_dump(mode='json')
        report=summarize(raw,request)
        self.assertEqual(report['planning_reason'],'feasible_candidate');self.assertEqual(report['improvement']['travel_minutes_saved'],90)
        for path,key,value in [('baseline','travel_minutes',0),('result','longest_leg_minutes',1)]:
            bad=deepcopy(raw);bad['planning_comparison'][path][key]=value
            with self.subTest(path=path),self.assertRaises(ValueError):summarize(bad,request)
        bad=deepcopy(raw);bad['planning_comparison']['baseline_days'][0]['stops'][0]['poi']['source'].pop('retrieved_at')
        with self.assertRaisesRegex(ValueError,'timestamp_missing'):summarize(bad,request)
        bad=deepcopy(raw);bad['planning_comparison']['result_poi_ids_by_day']=[['a','b']]
        with self.assertRaises(ValueError):summarize(bad,request)

    def test_async_api_events_receipt_adjustment_and_source_preservation(self):
        with api() as (client,_),patch('travel.tasks.run',alternative_worker):
            response=client.post('/api/v1/travel/tasks',json=REQUEST,headers={'Idempotency-Key':'TEST-ONLY-comparison'})
            parent=result(client,response)
            self.assertTrue(parent['planning_comparison']['applied'])
            again=client.post('/api/v1/travel/tasks',json=REQUEST,headers={'Idempotency-Key':'TEST-ONLY-comparison'})
            self.assertEqual(again.json()['id'],response.json()['id'])
            events=client.get('/api/v1/travel/tasks/'+response.json()['id']+'/events').json()['items']
            self.assertIn('selection_validated',[e['stage'] for e in events])
            path='/api/v1/travel/itineraries/'+parent['id']
            groups=[[s['poi']['id'] for s in day['stops']] for day in parent['days']]
            child=result(client,client.post(path+'/adjust',json={'poi_ids_by_day':groups,'stay_minutes_by_poi':{groups[0][0]:45}}))
            self.assertIsNone(child['planning_comparison']);self.assertEqual(child['parent_id'],parent['id'])
            self.assertEqual([[s['poi']['id'] for s in day['stops']] for day in child['days']],groups)
            self.assertEqual(client.get(path).json(),parent)

    def test_api_old_false_receipt_equivalence_and_opt_in_conflict(self):
        with api() as (client,_),patch('travel.tasks.run',alternative_worker):
            request={k:v for k,v in REQUEST.items() if k!='compare_poi_alternatives'}
            headers={'Idempotency-Key':'TEST-ONLY-legacy-choice'}
            first=client.post('/api/v1/travel/tasks',json=request,headers=headers);result(client,first)
            same=client.post('/api/v1/travel/tasks',json={**request,'compare_poi_alternatives':False},headers=headers)
            self.assertEqual(same.json()['id'],first.json()['id'])
            self.assertEqual(client.post('/api/v1/travel/tasks',json=REQUEST,headers=headers).status_code,409)
            self.assertEqual(client.post('/api/v1/travel/tasks',json={**request,'compare_poi_alternatives':'true'}).status_code,422)

    def test_audit_preserves_baseline_ids_sources_and_missing_rating_tradeoffs(self):
        raw=plan(PlanRequest(**REQUEST),lambda *_:None,provider=ReportAlternativeProvider()).model_dump(mode='json')
        audit=summarize(raw,REQUEST)['planning_evidence']
        self.assertEqual(audit['baseline_metrics']['travel_minutes'],100)
        self.assertEqual(audit['adopted_metrics']['travel_minutes'],10)
        self.assertEqual([p['id'] for p in audit['removed_pois']],['b'])
        self.assertEqual([p['id'] for p in audit['added_pois']],['c'])
        self.assertIsNone(audit['added_pois'][0]['rating'])
        self.assertEqual(audit['added_pois'][0]['source']['provider'],'amap')
        self.assertEqual(audit['subjective_quality_assessment'],'not_assessed')

    def test_practical_profile_preflight_accounts_for_all_proposals(self):
        cases=scenarios('practical','2026-10-23')
        self.assertEqual([c['maximum_provider_calls'] for c in cases],[17,49,25])
        self.assertTrue(all(c['request']['compare_poi_alternatives'] for c in cases))
        self.assertEqual(sum(c['maximum_provider_calls'] for c in cases),91)

if __name__=='__main__':unittest.main()
