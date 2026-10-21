"""Saved history tests use isolated TEST ONLY snapshots, never real providers."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import ItineraryQuery, PlanRequest
from travel.store import Store
from test_travel import FixtureProvider, PAYLOAD
from pagination_fixture import seed_history


class ListingTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'test.sqlite3';self.store=Store(self.path);self.addCleanup(self.store.close)
        self.template=plan(PlanRequest.model_validate(PAYLOAD),lambda *_:None,provider=FixtureProvider())
        self.history=seed_history(self.store,self.template,'alpha')
        self.foreign=seed_history(self.store,self.template,'beta',3)

    def page(self,owner='alpha',**kwargs):return self.store.itinerary_page(ItineraryQuery(**kwargs),owner_id=owner)

    def test_all_records_over_fifty_are_paged_exactly_once(self):
        page=self.page();self.assertEqual(len(page.items),50);self.assertEqual(page.total,65)
        second=self.page(cursor=page.next_cursor);self.assertEqual(len(second.items),15);self.assertIsNone(second.next_cursor)
        ids=[t.id for t in page.items+second.items]
        self.assertEqual(len(set(ids)),65);self.assertEqual(set(ids),{t.id for t in self.history})
        self.assertTrue(self.page(cursor=page.page_cursor).model_dump()==page.model_dump())
        self.assertEqual(len(self.store.itineraries(owner_id='alpha')),50)

    def test_literal_search_city_title_date_and_id_are_owner_scoped(self):
        self.assertEqual(self.page(query=' TEST ONLY 分页城市 ').total,65)
        self.assertEqual(self.page(query='历史分页 000').items[0].id,self.history[0].id)
        self.assertEqual(self.page(query=self.history[61].id.upper()).total,1)
        self.assertEqual(self.page(query='2026-01-01').total,7)
        for query in ['%', '_', "' OR 1=1 --", self.foreign[0].id, '\\']:
            self.assertEqual(self.page(query=query).total,0,query)

    def test_filters_and_direct_counts_use_full_owner_history(self):
        self.assertEqual(self.page(kind='original').total,63);self.assertEqual(self.page(kind='adjusted').total,2)
        root=self.history[0]
        page=self.page(query=root.id)
        self.assertEqual(page.direct_adjustment_counts,{root.id:1})
        direct=self.page(parent_id=root.id)
        self.assertEqual([t.id for t in direct.items],[self.history[60].id])
        self.assertEqual(self.page(parent_id=self.foreign[0].id).total,0)
        self.assertEqual(self.page(kind='original',parent_id=root.id).total,0)

    def test_each_sort_has_deterministic_ties_and_missing_dates_sort_last(self):
        for order in ('newest','oldest','departure'):
            first=self.page(order=order,limit=7)
            second=self.page(order=order,limit=7,cursor=first.next_cursor)
            self.assertFalse({t.id for t in first.items}&{t.id for t in second.items})
            self.assertEqual(first.model_dump(),self.page(order=order,limit=7,cursor=first.page_cursor).model_dump())
        self.assertEqual(self.page(order='oldest').items[0].created_at,'2026-01-01T00:00:00+00:00')
        departures=[t.request.start_date for t in self.page(order='departure').items]
        self.assertEqual(departures,sorted(departures))
        with self.store.db:
            value=self.history[0].model_dump(mode='json');value.pop('created_at')
            self.store.db.execute('UPDATE itineraries SET data=? WHERE id=?',(json.dumps(value),self.history[0].id))
        for order in ('newest','oldest'):
            first=self.page(order=order)
            last=self.page(order=order,cursor=first.next_cursor)
            self.assertEqual(last.items[-1].id,self.history[0].id)
            self.assertEqual(last.items[-1].created_at,'')
        self.assertEqual(self.store.itinerary(self.history[0].id).created_at,'')
        legacy=self.store.itineraries(100,owner_id='alpha')
        self.assertEqual(next(trip for trip in legacy if trip.id==self.history[0].id).created_at,'')

    def test_cursor_rejects_changed_owner_filter_sort_limit_and_malformed_values(self):
        cursor=self.page(limit=5).next_cursor
        for kwargs in [dict(owner='beta',limit=5),dict(limit=6),dict(limit=5,query='x'),dict(limit=5,kind='original'),dict(limit=5,order='oldest'),dict(limit=5,parent_id='x')]:
            with self.assertRaises(TravelFailure) as error:self.page(cursor=cursor,**kwargs)
            self.assertEqual(error.exception.status,422)
        data=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
        bad=[None,[],{**data,'v':True},{**data,'s':-1},{**data,'o':2**64},{**data,'o':True},{**data,'extra':1}]
        for value in ['@not-base64',*[base64.urlsafe_b64encode(json.dumps(item).encode()).decode() for item in bad]]:
            with self.assertRaises(TravelFailure):self.page(limit=5,cursor=value)

    def test_new_inserts_do_not_shift_next_previous_or_relationship_counts(self):
        first=self.page(limit=10,order='oldest')
        other=seed_history(self.store,self.template,'alpha-new',1)[0]
        with self.store.db:
            data=other.model_dump(mode='json');data['parent_id']=self.history[0].id
            self.store.db.execute('UPDATE itineraries SET data=? WHERE id=?',(json.dumps(data),other.id))
            self.store.db.execute("UPDATE resource_owners SET owner_id='alpha' WHERE kind='itinerary' AND resource_id=?",(other.id,))
        second=self.page(limit=10,order='oldest',cursor=first.next_cursor)
        self.assertEqual(second.total,65)
        self.assertEqual(self.page(limit=10,order='oldest',cursor=first.page_cursor).model_dump(),first.model_dump())
        self.assertEqual(self.page(query=self.history[0].id).direct_adjustment_counts[self.history[0].id],2)
        self.assertEqual(self.page().total,66)

    def test_cursor_survives_reopen_without_changing_records(self):
        first=self.page(limit=3)
        reopened=Store(self.path)
        try:
            next_page=reopened.itinerary_page(ItineraryQuery(limit=3,cursor=first.next_cursor),owner_id='alpha')
            self.assertEqual(next_page.total,65)
            self.assertEqual(reopened.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(reopened.itinerary(self.history[0].id).model_dump(),self.history[0].model_dump())
        finally:reopened.close()


class ListingHttpTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(folder.cleanup)
        env=patch.dict(os.environ,{'TRAVEL_DB_PATH':str(Path(folder.name)/'test.sqlite3'),'TRAVEL_AUTH_MODE':'session','TRAVEL_COOKIE_SECURE':'0','TRAVEL_PRODUCTION':'1'})
        env.start();self.addCleanup(env.stop)
        from main import app
        self.client=TestClient(app).__enter__();self.addCleanup(lambda:self.client.__exit__(None,None,None))
        self.headers={};self.history={}
        template=plan(PlanRequest.model_validate(PAYLOAD),lambda *_:None,provider=FixtureProvider())
        for name in ('alpha','beta'):
            user=app.state.auth.create_user('test-list-'+name,'TEST ONLY listing password 2026')
            response=self.client.post('/api/v1/travel/auth/login',json={'username':user.username,'password':'TEST ONLY listing password 2026','transport':'bearer'})
            self.assertEqual(response.status_code,200)
            self.headers[name]={'Authorization':'Bearer '+response.json()['access_token']}
            self.history[name]=seed_history(app.state.travel.store,template,user.id)

    def get(self,owner='alpha',**query):return self.client.get('/api/v1/travel/itineraries',params=query,headers=self.headers[owner])

    def test_http_defaults_legacy_items_and_validation(self):
        response=self.get();self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(len(data['items']),50);self.assertEqual(data['total'],65)
        for query in [dict(limit=0),dict(limit=101),dict(query='x'*121),dict(kind='invalid'),dict(order='invalid'),dict(cursor='@'),dict(parent_id=''),dict(unknown='x')]:
            invalid=self.get(**query);self.assertEqual(invalid.status_code,422,invalid.text)
            self.assertIn('error',invalid.json())
        self.assertEqual(self.client.get('/api/v1/travel/itineraries').status_code,401)

    def test_http_foreign_search_parent_counts_and_cursor_stay_isolated(self):
        own=self.get(query=self.history['alpha'][0].id).json()
        self.assertEqual(own['total'],1);self.assertEqual(list(own['direct_adjustment_counts'].values()),[1])
        self.assertEqual(self.get(query=self.history['beta'][0].id).json()['total'],0)
        self.assertEqual(self.get(parent_id=self.history['beta'][0].id).json()['total'],0)
        cursor=self.get(limit=2).json()['next_cursor']
        denied=self.get(owner='beta',limit=2,cursor=cursor)
        self.assertEqual(denied.status_code,422)
        self.assertEqual(denied.json()['error']['code'],'invalid_itinerary_cursor')
        own_page=self.get(limit=2,cursor=cursor).json();self.assertEqual(own_page['total'],65)
        self.assertTrue(all('alpha' in t['title'] or t['id'] in {v.id for v in self.history['alpha']} for t in own_page['items']))


if __name__=='__main__':unittest.main()
