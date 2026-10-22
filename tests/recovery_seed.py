"""Explicit TEST ONLY records for an archived-service recovery drill, never an API fallback."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-fixtures-only',action='store_true',required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--phase',choices=['initial','pending','mutate'],required=True)
    args=parser.parse_args();source=args.source.resolve();db=args.db.resolve()
    boundary=(ROOT/'.tmp').resolve()
    if not source.is_relative_to(boundary) or not db.is_relative_to(boundary) or not (source/'backend/main.py').is_file():
        parser.error('Only extracted TEST ONLY sources and databases below this repository .tmp are allowed')
    if args.phase=='initial' and db.exists():parser.error('Initial seed never overwrites an existing database')
    if args.phase!='initial' and not db.is_file():parser.error('Existing test database required')
    sys.path[:0]=[str(source/'backend'),str(source/'tests')]
    from travel.auth import AuthService
    from travel.planner import plan
    from agent.travel_intake import finish_draft
    from travel.drafts import clarify
    from travel.schemas import DraftClarificationRequest, DraftRequest, DraftSubmission, PlanRequest, Task
    from travel.store import Store
    from test_poi_comparison import RatingAlternativeProvider
    store=Store(db)
    identifiers={}
    try:
        if args.phase=='initial':
            auth=AuthService(store)
            for name in ('alpha','beta'):
                user=auth.create_user('test-'+name,'TEST ONLY recovery password 2026')
                request=PlanRequest(city='TEST ONLY',query='公园',start_date='2026-10-20',days=1,stops_per_day=2,stay_minutes=30,
                    compare_poi_alternatives=True,day_schedules=[{'day_start':'09:30','day_end':'18:30','stay_minutes':30}],
                    max_leg_travel_minutes=120,max_daily_travel_minutes=180)
                task=Task(id='test-only-'+name,status='running')
                store.register_task(task,{'request':request.model_dump(mode='json')},'test-only-'+name,'TEST ONLY',owner_id=user.id)
                trip=plan(request,lambda *_:None,provider=RatingAlternativeProvider())
                if not trip.planning_comparison.applied:raise AssertionError('TEST ONLY comparison must exercise factual baseline preservation')
                store.succeed(task,trip)
                groups=[[stop.poi.id for stop in day.stops] for day in trip.days]
                changed=request.model_copy(update={'budget':0,'user_prices':{groups[0][0]:0},'stay_minutes_by_poi':{groups[0][0]:45}})
                child_task=Task(id='test-only-'+name+'-adjust',status='running')
                payload={'request':changed.model_dump(mode='json'),'poi_ids_by_day':groups,'optimize_order':False,'parent_id':trip.id}
                store.register_task(child_task,payload,'test-only-'+name+'-adjust','TEST ONLY',owner_id=user.id)
                child=plan(changed,lambda *_:None,provider=RatingAlternativeProvider(),poi_ids_by_day=groups,optimize_order=False,parent_id=trip.id)
                store.succeed(child_task,child)
                intake=DraftRequest(text='TEST ONLY 公园；第一天九点开始；每段不超过40分钟；从待选酒店出发，需要预约',reference_date='2026-10-20')
                draft=finish_draft(intake,DraftSubmission(values={'query':'公园','day_schedules':[{'day_start':'09:00'}],
                    'max_leg_travel_minutes':40,'origin_hint':'待选酒店'},evidence={'query':'公园','day_schedules':'第一天九点开始',
                    'max_leg_travel_minutes':'每段不超过40分钟','origin_hint':'待选酒店'},unhandled_requirements=['需要预约']),lambda *_:None)
                draft_task=Task(id='test-only-'+name+'-draft',status='running',kind='draft')
                store.register_task(draft_task,{'kind':'draft','request':intake.model_dump(mode='json')},'test-only-'+name+'-draft','TEST ONLY',owner_id=user.id)
                store.succeed_draft(draft_task,draft)
                for revision,values in ((1,{'city':'TEST ONLY '+name,'start_date':'2026-10-20','days':1}),
                    (2,{'max_daily_travel_minutes':90,'destination_hint':'TEST ONLY 待选车站'})):
                    draft=clarify(draft,DraftClarificationRequest(expected_revision=revision,values=values,
                        confirm_fields=['query'] if revision==1 else []))
                    store.update_draft(draft,revision,owner_id=user.id)
                identifiers[name]={'itinerary_ids':[trip.id,child.id],'parent_id':trip.id,'child_id':child.id,'draft_id':draft.id,
                    'receipt_keys':['test-only-'+name,'test-only-'+name+'-adjust','test-only-'+name+'-draft']}
        else:
            user=store.db.execute("SELECT id FROM auth_users WHERE username='test-beta'").fetchone()[0]
            if args.phase=='pending':
                request=PlanRequest(city='TEST ONLY pending',query='TEST ONLY recovery',start_date='2026-10-20',days=1,stops_per_day=2)
                task=Task(id='test-only-interrupted',status='running')
                store.register_task(task,{'request':request.model_dump(mode='json')},'test-only-pending','TEST ONLY',owner_id=user)
                store.event(task.id,'running','TEST ONLY persisted unfinished task; no synthetic worker')
            else:
                row=store.db.execute("SELECT i.id,i.data FROM itineraries i JOIN resource_owners o ON o.resource_id=i.id AND o.kind='itinerary' WHERE o.owner_id=? ORDER BY i.rowid DESC LIMIT 1",(user,)).fetchone()
                from travel.schemas import Itinerary
                trip=Itinerary.model_validate_json(row[1]);trip.title='TEST ONLY post-snapshot change'
                with store.db:store.db.execute('UPDATE itineraries SET data=? WHERE id=?',(trip.model_dump_json(),trip.id))
        print(json.dumps({'seeded':args.phase,'source':'TEST ONLY offline records, never production provider','owners':identifiers}))
    finally:store.close()


if __name__=='__main__':main()
