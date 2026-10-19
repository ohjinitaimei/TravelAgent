"""Authentication and cross-user isolation using explicit TEST ONLY records."""
import json
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from travel.auth import COOKIE, AuthService, password_hash, password_matches, token_hash
from travel.schemas import PlanRequest, Task
from travel.store import Store
from test_travel import PAYLOAD, FixtureProvider, fixture_worker
from test_agent_intake import TEXT, draft_fixture_worker

PASSWORD='TEST ONLY account password 2026'
BASE='/api/v1/travel'


def authenticated_fixture_worker(payload,output):
    return draft_fixture_worker(payload,output) if payload.get('kind')=='draft' else fixture_worker(payload,output)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(self.folder.cleanup)
        self.env=patch.dict(os.environ,{'TRAVEL_AUTH_MODE':'session','TRAVEL_COOKIE_SECURE':'0','TRAVEL_DB_PATH':str(Path(self.folder.name)/'test.sqlite3'),'TRAVEL_PRODUCTION':'0','TRAVEL_TOOL_TRANSPORT':'direct'})
        self.env.start();self.addCleanup(self.env.stop)
        self.worker=patch('travel.tasks.run',authenticated_fixture_worker)
        self.worker.start();self.addCleanup(self.worker.stop)
        from main import app
        self.app=app
        self.client=TestClient(app).__enter__()
        self.addCleanup(lambda:self.client.__exit__(None,None,None))
        self.auth=app.state.auth
        self.alpha=self.auth.create_user('test-alpha',PASSWORD)
        self.beta=self.auth.create_user('test-beta',PASSWORD)
        self.a=self.login('test-alpha')['access_token']
        self.b=self.login('test-beta')['access_token']
        self.ah={'Authorization':'Bearer '+self.a}
        self.bh={'Authorization':'Bearer '+self.b}

    def login(self,name,**kwargs):
        response=self.client.post(BASE+'/auth/login',json={'username':name,'password':PASSWORD,'transport':'bearer',**kwargs})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def wait(self,identifier,headers):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            response=self.client.get(BASE+'/tasks/'+identifier,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            task=response.json()
            if task['status'] not in {'queued','running'}: return task
            time.sleep(.05)
        self.fail('Task did not finish')

    def test_unauthenticated_routes_and_legacy_bypasses_are_closed(self):
        for method,path,body in [('GET','/capabilities',None),('GET','/itineraries',None),('GET','/tasks/unknown',None),('GET','/tasks/unknown/events/stream',None),('POST','/tool-service/check',None),('POST','/tasks',PAYLOAD),('POST','/drafts',{'text':TEXT,'reference_date':'2026-10-19'})]:
            response=self.client.request(method,BASE+path,json=body)
            self.assertEqual(response.status_code,401,(path,response.text))
            self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.client.post('/api/intent/parse',json={'query':'TEST ONLY'}).status_code,410)
        self.assertEqual(self.client.post('/api/context/events',json={}).status_code,410)
        status=self.client.get(BASE+'/auth/status').json()
        self.assertFalse(status['authenticated'])
        self.assertFalse(status['setup_required'])

    def test_task_receipts_events_itineraries_and_edits_are_isolated(self):
        shared={'Idempotency-Key':'test-only-shared-key'}
        a=self.client.post(BASE+'/tasks',json=PAYLOAD,headers={**self.ah,**shared}).json()
        b=self.client.post(BASE+'/tasks',json={**PAYLOAD,'city':'TEST ONLY beta'},headers={**self.bh,**shared}).json()
        self.assertNotEqual(a['id'],b['id'])
        for headers,identifier in [(self.ah,a['id']),(self.bh,b['id'])]:
            self.assertEqual(self.client.get(BASE+'/submissions/test-only-shared-key',headers=headers).json()['id'],identifier)
        final_a=self.wait(a['id'],self.ah);final_b=self.wait(b['id'],self.bh)
        self.assertEqual(final_a['status'],'succeeded',final_a)
        self.assertEqual(final_b['status'],'succeeded',final_b)
        for suffix in ('','/events','/events/stream'):
            self.assertEqual(self.client.get(BASE+'/tasks/'+a['id']+suffix,headers=self.bh).status_code,404)
        for suffix in ('/cancel','/retry'):
            self.assertEqual(self.client.post(BASE+'/tasks/'+a['id']+suffix,headers=self.bh).status_code,404)
        trip=final_a['itinerary_id']
        edit={'poi_ids_by_day':[['fixture-a','fixture-b']],'user_prices':{'fixture-a':20}}
        self.assertEqual(self.client.get(BASE+'/itineraries/'+trip,headers=self.bh).status_code,404)
        self.assertEqual(self.client.post(BASE+'/itineraries/'+trip+'/adjust',headers=self.bh,json=edit).status_code,404)
        adjusted=self.client.post(BASE+'/itineraries/'+trip+'/adjust',headers=self.ah,json=edit).json()
        new=self.wait(adjusted['id'],self.ah)
        self.assertEqual(new['status'],'succeeded',new)
        self.assertEqual(len(self.client.get(BASE+'/itineraries',headers=self.ah).json()['items']),2)
        self.assertEqual(len(self.client.get(BASE+'/itineraries',headers=self.bh).json()['items']),1)
        self.assertEqual(self.app.state.travel.store.owner('itinerary',new['itinerary_id']),self.alpha.id)
        self.assertEqual(self.client.post(BASE+'/tasks',json={**PAYLOAD,'owner_id':self.alpha.id},headers=self.bh).status_code,422)

    def test_unique_submission_key_is_not_visible_to_another_user(self):
        task=self.client.post(BASE+'/tasks',json=PAYLOAD,headers={**self.ah,'Idempotency-Key':'test-only-alpha-receipt'}).json()
        self.assertEqual(self.client.get(BASE+'/submissions/test-only-alpha-receipt',headers=self.bh).status_code,404)
        own=self.client.get(BASE+'/submissions/test-only-alpha-receipt',headers=self.ah)
        self.assertEqual(own.json()['id'],task['id'])

    def test_draft_updates_remain_owned_after_clarification(self):
        task=self.client.post(BASE+'/drafts',headers=self.ah,json={'text':TEXT,'reference_date':'2026-10-19'}).json()
        final=self.wait(task['id'],self.ah)
        self.assertEqual(final['status'],'succeeded',final)
        path=BASE+'/drafts/'+final['draft_id']
        update={'expected_revision':1,'values':{'budget':0},'confirm_fields':['budget']}
        self.assertEqual(self.client.get(path,headers=self.bh).status_code,404)
        self.assertEqual(self.client.patch(path,headers=self.bh,json=update).status_code,404)
        saved=self.client.patch(path,headers=self.ah,json=update)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['revision'],2)
        self.assertEqual(self.app.state.travel.store.owner('draft',final['draft_id']),self.alpha.id)

    def test_retry_preserves_owner_and_does_not_modify_original(self):
        task=self.client.post(BASE+'/tasks',json=PAYLOAD,headers=self.ah).json()
        self.client.post(BASE+'/tasks/'+task['id']+'/cancel',headers=self.ah)
        denied=self.client.post(BASE+'/tasks/'+task['id']+'/retry',headers=self.bh)
        self.assertEqual(denied.status_code,404)
        new=self.client.post(BASE+'/tasks/'+task['id']+'/retry',headers=self.ah).json()
        self.assertEqual(new['retry_of'],task['id'])
        self.assertEqual(self.wait(new['id'],self.ah)['status'],'succeeded')
        self.assertEqual(self.client.get(BASE+'/tasks/'+task['id'],headers=self.ah).json()['status'],'cancelled')

    def test_cookie_csrf_origin_identity_and_logout(self):
        response=self.client.post(BASE+'/auth/login',headers={'X-Travel-Client':'web','Origin':'http://localhost:5173'},json={'username':'test-alpha','password':PASSWORD})
        self.assertEqual(response.status_code,200,response.text)
        value=response.json();token=self.client.cookies[COOKIE]
        self.assertIsNone(value['access_token'])
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=strict',response.headers['set-cookie'])
        self.assertEqual(self.client.post(BASE+'/tasks',json=PAYLOAD).status_code,403)
        self.assertEqual(self.client.post(BASE+'/tasks',json=PAYLOAD,headers=[(b'X-CSRF-Token',b'\xff')]).status_code,403)
        self.assertEqual(self.client.get(BASE+'/capabilities',headers={'Authorization':'Basic TEST_ONLY'}).status_code,401)
        headers={'X-CSRF-Token':value['csrf_token'],'X-Workspace-User':self.alpha.id}
        self.assertEqual(self.client.post(BASE+'/tasks',json=PAYLOAD,headers={**headers,'Origin':'https://test.invalid'}).status_code,403)
        self.assertEqual(self.client.post(BASE+'/tasks',json=PAYLOAD,headers={**headers,'X-Workspace-User':self.beta.id}).status_code,409)
        task=self.client.post(BASE+'/tasks',json=PAYLOAD,headers=headers)
        self.assertEqual(task.status_code,202,task.text)
        self.assertEqual(self.client.post(BASE+'/auth/logout',headers=headers).status_code,200)
        self.assertNotIn(COOKIE,self.client.cookies)
        self.assertEqual(self.client.get(BASE+'/capabilities',headers={'Authorization':'Bearer '+token}).status_code,401)
        self.assertEqual(self.client.get(BASE+'/capabilities',headers=self.bh).status_code,200)

    def test_password_reset_disable_and_session_expiration_revoke_access(self):
        self.auth.reset_password('test-alpha',PASSWORD+' changed')
        self.assertEqual(self.client.get(BASE+'/capabilities',headers=self.ah).status_code,401)
        new=self.login('test-alpha',password=PASSWORD+' changed')['access_token']
        with self.auth.store.lock,self.auth.store.db:
            self.auth.store.db.execute('UPDATE auth_sessions SET last_seen=0 WHERE digest=?',(token_hash(new),))
        self.assertEqual(self.client.get(BASE+'/capabilities',headers={'Authorization':'Bearer '+new}).status_code,401)
        expired=self.login('test-alpha',password=PASSWORD+' changed')['access_token']
        with self.auth.store.lock,self.auth.store.db:
            self.auth.store.db.execute('UPDATE auth_sessions SET expires_at=0 WHERE digest=?',(token_hash(expired),))
        self.assertFalse(self.client.get(BASE+'/auth/status',headers={'Authorization':'Bearer '+expired}).json()['authenticated'])
        self.auth.disable_user('test-beta')
        self.assertEqual(self.client.get(BASE+'/capabilities',headers=self.bh).status_code,401)
        self.assertEqual(self.client.post(BASE+'/auth/login',json={'username':'test-beta','password':PASSWORD,'transport':'bearer'}).status_code,401)
        self.auth.enable_user('test-beta')
        self.assertEqual(self.client.get(BASE+'/capabilities',headers=self.bh).status_code,401)
        self.assertTrue(self.login('test-beta')['authenticated'])

    def test_storage_contains_only_hashes_and_login_errors_do_not_enumerate(self):
        wrong=self.client.post(BASE+'/auth/login',json={'username':'test-alpha','password':'TEST ONLY wrong','transport':'bearer'})
        missing=self.client.post(BASE+'/auth/login',json={'username':'test-missing','password':'TEST ONLY wrong','transport':'bearer'})
        self.assertEqual(wrong.status_code,401)
        self.assertEqual(wrong.json(),missing.json())
        with self.auth.store.lock:
            dump='\n'.join(self.auth.store.db.iterdump())
        self.assertNotIn(PASSWORD,dump)
        self.assertNotIn(self.a,dump)
        self.assertIn('scrypt$131072$8$1$',dump)
        digest=password_hash(PASSWORD)
        self.assertTrue(password_matches(PASSWORD,digest))
        self.assertFalse(password_matches('TEST ONLY wrong',digest))

    def test_login_limits_and_session_cap(self):
        for _ in range(6): last=self.login('test-alpha')['access_token']
        self.assertIsNone(self.auth.resolve(self.a,'bearer'))
        self.assertIsNotNone(self.auth.resolve(last,'bearer'))
        for _ in range(3):
            self.client.post(BASE+'/auth/login',json={'username':'test-alpha','password':'TEST ONLY wrong','transport':'bearer'})
        limited=self.client.post(BASE+'/auth/login',json={'username':'test-alpha','password':PASSWORD,'transport':'bearer'})
        self.assertEqual(limited.status_code,429)
        self.assertEqual(limited.json()['error']['code'],'login_rate_limited')

    def test_old_database_stays_local_until_explicit_operator_claim(self):
        from travel.accounts import claim_local
        from travel.planner import plan
        path=Path(self.folder.name)/'legacy.sqlite3'
        store=Store(path)
        trip=plan(PlanRequest.model_validate(PAYLOAD),lambda *_:None,provider=FixtureProvider())
        store.succeed(Task(id='test-legacy',status='running'),trip)
        store.db.execute("INSERT INTO submission_keys VALUES ('test-legacy-key','test-only','test-legacy')")
        store.db.execute('DELETE FROM resource_owners');store.db.commit();store.close()
        store=Store(path)
        try:
            auth=AuthService(store);user=auth.create_user('test-owner',PASSWORD)
            self.assertEqual(store.itineraries(owner_id=user.id),[])
            self.assertEqual(len(store.itineraries()),1)
            claim_local(store,'test-owner')
            self.assertEqual(store.itineraries(owner_id=user.id)[0].id,trip.id)
            self.assertIsNone(store.submission('test-legacy-key'))
            self.assertEqual(store.submission('test-legacy-key',owner_id=user.id).id,'test-legacy')
        finally: store.close()
        store=Store(path)
        try: self.assertEqual(store.itineraries(owner_id=user.id)[0].id,trip.id)
        finally: store.close()

    def test_stream_rechecks_session_after_revocation(self):
        from starlette.requests import Request
        from travel.auth import require_user
        from travel.api import stream
        store=self.app.state.travel.store
        task=Task(id='test-only-sse-session',status='running')
        store.register_task(task,{'request':PAYLOAD},None,'test-only',owner_id=self.alpha.id)
        store.event(task.id,'running','TEST ONLY')
        async def check():
            async def receive():
                await asyncio.sleep(60)
                return {'type':'http.disconnect'}
            request=Request({'type':'http','method':'GET','path':BASE+'/tasks/'+task.id+'/events/stream','headers':[(b'authorization',('Bearer '+self.a).encode())],'app':self.app},receive=receive)
            require_user(request)
            response=await stream(task.id,request,after=0,last_event_id=None)
            self.assertIn('event: progress',await anext(response.body_iterator))
            self.auth.revoke(self.a)
            self.assertIn('event: auth_required',await anext(response.body_iterator))
            with self.assertRaises(StopAsyncIteration): await anext(response.body_iterator)
        asyncio.run(check())

    def test_cookie_rotation_secure_cookie_and_login_origin(self):
        def cookie_login(name):
            return self.client.post(BASE+'/auth/login',headers={'X-Travel-Client':'web'},json={'username':name,'password':PASSWORD})
        self.assertEqual(cookie_login('test-alpha').status_code,200)
        old=self.client.cookies[COOKIE]
        self.assertEqual(cookie_login('test-beta').status_code,200)
        self.assertIsNone(self.auth.resolve(old,'cookie'))
        self.assertEqual(self.client.get(BASE+'/auth/status').json()['user']['id'],self.beta.id)
        self.assertEqual(self.client.get(BASE+'/capabilities',headers={'X-Workspace-User':self.alpha.id}).status_code,409)
        denied=self.client.post(BASE+'/auth/login',headers={'X-Travel-Client':'web','Origin':'https://test.invalid'},json={'username':'test-alpha','password':PASSWORD})
        self.assertEqual(denied.status_code,403)
        self.auth.secure=True
        self.assertEqual(cookie_login('test-alpha').status_code,503)
        self.client.base_url='https://testserver'
        secure=cookie_login('test-alpha')
        self.assertEqual(secure.status_code,200,secure.text)
        self.assertIn('; Secure',secure.headers['set-cookie'])

    def test_claim_conflicts_do_not_change_resource_ownership(self):
        from travel.accounts import claim_local
        store=self.auth.store
        for owner in ('local',self.alpha.id):
            store.register_task(Task(id='test-conflict-'+owner,status='failed'),{'request':PAYLOAD},'test-claim-key','test-only',owner_id=owner)
        with self.assertRaises(ValueError): claim_local(store,'test-alpha')
        self.assertTrue(store.owns('task','test-conflict-local','local'))
        self.assertIsNotNone(store.submission('test-claim-key'))

    def test_invalid_configuration_does_not_silently_disable_auth(self):
        for settings in ({'TRAVEL_AUTH_MODE':'unexpected'},{'TRAVEL_SESSION_TTL':'0'},{'TRAVEL_CORS_ORIGINS':'*'}):
            with patch.dict(os.environ,settings),self.assertRaises(ValueError): AuthService(self.auth.store)


if __name__=='__main__':
    (ROOT/'.tmp').mkdir(exist_ok=True)
    unittest.main()
