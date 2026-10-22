"""TEST ONLY shared pacing: isolated SQLite, fake HTTP, real child processes."""
from contextlib import closing
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from travel.provider_gate import GateFailure, ProviderGate, rate_path
from travel.provider import AmapProvider, TravelFailure


def admission(path,ready,start,output,interval):
    ready.put(True)
    start.wait(10)
    ProviderGate(path,interval=interval,max_wait=3).acquire()
    output.put(time.time())


def blocked(path,ready):
    ready.set()
    ProviderGate(path,interval=5,max_wait=5).acquire()


def rate_worker(payload,output):
    # Exercise the production worker's Error serialization without a live API.
    from travel.worker import run
    def reject(*args,**kwargs):
        raise TravelFailure('provider_rate_limited','TEST ONLY limited',True,429,retry_after=3)
    with patch('travel.worker.plan',reject):run(payload,output)


class ProviderGateTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'rate.sqlite3'

    def test_spawned_processes_share_start_spacing(self):
        context=mp.get_context('spawn');ready=context.Queue();output=context.Queue();start=context.Event()
        children=[context.Process(target=admission,args=(str(self.path),ready,start,output,.15)) for _ in range(4)]
        try:
            for child in children:child.start()
            for _ in children:ready.get(timeout=15)
            start.set()
            starts=sorted(output.get(timeout=10) for _ in children)
            self.assertTrue(all(b-a>=.13 for a,b in zip(starts,starts[1:])),starts)
            for child in children:child.join(5);self.assertEqual(child.exitcode,0)
        finally:
            for child in children:
                if child.is_alive():child.terminate();child.join(5)
            ready.close();ready.join_thread();output.close();output.join_thread()

    def test_killed_waiter_does_not_reserve_future_slots(self):
        gate=ProviderGate(self.path,interval=5,max_wait=5);gate.acquire()
        with closing(sqlite3.connect(self.path)) as db:
            before=db.execute('SELECT next_at FROM pacing').fetchone()[0]
        context=mp.get_context('spawn');ready=context.Event()
        child=context.Process(target=blocked,args=(str(self.path),ready))
        try:
            child.start();self.assertTrue(ready.wait(15));time.sleep(.2)
        finally:
            if child.is_alive():child.terminate()
            child.join(5)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT next_at FROM pacing').fetchone()[0],before)
            db.execute('UPDATE pacing SET next_at=0');db.commit()
        gate.acquire()

    def test_wait_is_bounded_and_does_not_hold_database_lock(self):
        gate=ProviderGate(self.path,interval=1,max_wait=.1);gate.acquire()
        started=time.monotonic()
        with self.assertRaises(GateFailure) as caught:gate.acquire()
        self.assertEqual(caught.exception.code,'provider_busy')
        self.assertLess(time.monotonic()-started,.5)
        with closing(sqlite3.connect(self.path,timeout=.1)) as db:
            db.execute('BEGIN IMMEDIATE');db.rollback()

    def test_busy_database_has_bounded_failure_and_other_errors_fail_closed(self):
        gate=ProviderGate(self.path,max_wait=.1);gate.acquire()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('BEGIN IMMEDIATE')
            started=time.monotonic()
            with self.assertRaises(GateFailure) as caught:gate.acquire()
            self.assertEqual(caught.exception.code,'provider_busy')
            self.assertLess(time.monotonic()-started,.5)
            db.rollback()
        self.path.write_bytes(b'TEST ONLY corrupt database')
        with self.assertRaises(GateFailure) as caught:gate.acquire()
        self.assertEqual(caught.exception.code,'provider_gate_unavailable')
        self.assertNotIn(str(self.path),str(caught.exception))

    def test_qps_rejection_is_shared_without_replaying_upstream_request(self):
        client=Mock(enabled=True);client.search_poi.return_value={'status':'0','infocode':'10021'}
        for _ in range(2):
            provider=AmapProvider(client,gate=ProviderGate(self.path,cooldown=1))
            with self.assertRaises(TravelFailure) as caught:provider.search('TEST ONLY','TEST ONLY')
            self.assertEqual((caught.exception.code,caught.exception.status),('provider_rate_limited',429))
            self.assertTrue(caught.exception.retryable);self.assertEqual(caught.exception.retry_after,1)
        self.assertEqual(client.search_poi.call_count,1)
        time.sleep(1.05)
        client.search_poi.return_value={'status':'1','pois':[]}
        self.assertEqual(AmapProvider(client,gate=ProviderGate(self.path)).search('TEST ONLY','TEST ONLY'),[])
        self.assertEqual(client.search_poi.call_count,2) # Explicit call after cooldown.

    def test_daily_quota_and_authorization_errors_do_not_become_short_cooldown(self):
        for code in ['10044','10001','SECRET?key=TEST_ONLY']:
            with self.subTest(code=code):
                gate=Mock();client=Mock(enabled=True)
                client.search_poi.return_value={'status':'0','infocode':code}
                with self.assertRaises(TravelFailure) as caught:AmapProvider(client,gate=gate).search('x','y')
                self.assertEqual(caught.exception.code,'provider_rejected')
                self.assertFalse(caught.exception.retryable);self.assertIsNone(caught.exception.retry_after)
                self.assertNotIn('SECRET',str(caught.exception));gate.rejected.assert_not_called()

    def test_invalid_settings_fail_before_http_and_paths_match_bundled_mcp(self):
        from travel.mcp_client import bundled_parameters
        for value in ['nan','inf','0','6','TEST ONLY']:
            with self.subTest(value=value),patch.dict(os.environ,{'TRAVEL_AMAP_MIN_INTERVAL_SECONDS':value}):
                client=Mock(enabled=True)
                with self.assertRaises(TravelFailure) as caught:AmapProvider(client).search('x','y')
                self.assertEqual(caught.exception.code,'invalid_provider_gate_config')
                self.assertFalse(caught.exception.retryable);client.search_poi.assert_not_called()
        with patch.dict(os.environ,{'TRAVEL_DB_PATH':str(self.path.parent/'business.sqlite3'),'TRAVEL_AMAP_RATE_DB_PATH':''}):
            params=bundled_parameters()
            self.assertEqual(Path(params.env['TRAVEL_AMAP_RATE_DB_PATH']),rate_path())
            self.assertNotIn('TRAVEL_DB_PATH',params.env)
        with patch.dict(os.environ,{'TRAVEL_DB_PATH':str(self.path),'TRAVEL_AMAP_RATE_DB_PATH':str(self.path)}):
            with self.assertRaises(GateFailure):ProviderGate.from_env()
        self.assertFalse(self.path.exists())

    def test_rest_and_worker_preserve_wait_hint_without_automatic_task_retry(self):
        from fastapi.testclient import TestClient
        from main import app
        from test_travel import PAYLOAD
        env={'TRAVEL_DB_PATH':str(self.path.parent/'api.sqlite3'),'TRAVEL_AUTH_MODE':'local'}
        with patch.dict(os.environ,env),patch('travel.tasks.run',rate_worker),TestClient(app) as client:
            error=TravelFailure('provider_rate_limited','TEST ONLY limited',True,429,retry_after=3)
            with patch('travel.provider.AmapProvider.search',side_effect=error):
                response=client.get('/api/v1/travel/pois',params={'keyword':'TEST ONLY','city':'TEST ONLY'})
            self.assertEqual(response.status_code,429,response.text)
            self.assertEqual(response.headers['Retry-After'],'3')
            self.assertEqual(response.json()['error']['retry_after'],3)
            task=client.post('/api/v1/travel/tasks',json=PAYLOAD).json()
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                final=client.get('/api/v1/travel/tasks/'+task['id']).json()
                if final['status'] not in {'queued','running'}:break
                time.sleep(.05)
            self.assertEqual(final['status'],'failed',final)
            self.assertEqual(final['error']['retry_after'],3)
            self.assertIsNone(final['itinerary_id'])
            time.sleep(.15)
            self.assertEqual(client.get('/api/v1/travel/tasks/'+task['id']).json()['status'],'failed')


if __name__=='__main__':
    (ROOT/'.tmp').mkdir(exist_ok=True)
    unittest.main()
