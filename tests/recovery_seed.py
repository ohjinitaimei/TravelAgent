"""Explicit TEST ONLY records for an archived-service recovery drill, never an API fallback."""
import argparse
import json
import os
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
    from travel.schemas import PlanRequest, Task
    from travel.store import Store
    from test_travel import FixtureProvider
    store=Store(db)
    try:
        if args.phase=='initial':
            auth=AuthService(store)
            for name in ('alpha','beta'):
                user=auth.create_user('test-'+name,'TEST ONLY recovery password 2026')
                request=PlanRequest(city='TEST ONLY '+name,query='TEST ONLY recovery',start_date='2026-10-20',days=1,stops_per_day=2)
                task=Task(id='test-only-'+name,status='running')
                store.register_task(task,{'request':request.model_dump(mode='json')},'test-only-'+name,'TEST ONLY',owner_id=user.id)
                trip=plan(request,lambda *_:None,provider=FixtureProvider())
                store.succeed(task,trip)
        else:
            user=store.db.execute("SELECT id FROM auth_users WHERE username='test-beta'").fetchone()[0]
            if args.phase=='pending':
                request=PlanRequest(city='TEST ONLY pending',query='TEST ONLY recovery',start_date='2026-10-20',days=1,stops_per_day=2)
                task=Task(id='test-only-interrupted',status='running')
                store.register_task(task,{'request':request.model_dump(mode='json')},'test-only-pending','TEST ONLY',owner_id=user)
                store.event(task.id,'running','TEST ONLY persisted unfinished task; no synthetic worker')
            else:
                row=store.db.execute("SELECT i.id,i.data FROM itineraries i JOIN resource_owners o ON o.resource_id=i.id AND o.kind='itinerary' WHERE o.owner_id=?",(user,)).fetchone()
                from travel.schemas import Itinerary
                trip=Itinerary.model_validate_json(row[1]);trip.title='TEST ONLY post-snapshot change'
                with store.db:store.db.execute('UPDATE itineraries SET data=? WHERE id=?',(trip.model_dump_json(),trip.id))
        print(json.dumps({'seeded':args.phase,'source':'TEST ONLY offline records, never production provider'}))
    finally:store.close()


if __name__=='__main__':main()
