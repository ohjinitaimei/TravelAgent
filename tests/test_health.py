"""Health probes use isolated databases; never call authorized providers."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from travel.health import router


class HealthTests(unittest.TestCase):
    def test_public_probes_in_session_mode_do_not_return_configuration(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder,patch.dict(os.environ,{
            'TRAVEL_DB_PATH':str(Path(folder)/'health.sqlite3'),'TRAVEL_AUTH_MODE':'session',
            'TRAVEL_COOKIE_SECURE':'1'}):
            from main import app
            with TestClient(app) as client,patch.object(app.state.map_proxy,'fetch',side_effect=AssertionError('No egress')):
                for path,status in [('/health/live','alive'),('/health/ready','ready')]:
                    r=client.get(path)
                    self.assertEqual(r.status_code,200);self.assertEqual(r.json(),{'status':status})
                    self.assertEqual(r.headers['cache-control'],'no-store')
                    self.assertNotIn('set-cookie',r.headers)
                self.assertEqual(client.get('/api/v1/travel/itineraries').status_code,401)
                self.assertNotIn('/health/ready',app.openapi()['paths'])

    def test_before_startup_is_live_but_not_ready(self):
        app=FastAPI();app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get('/health/live').status_code,200)
            self.assertEqual(client.get('/health/ready').json(),{'status':'unavailable'})
            self.assertEqual(client.get('/health/ready').status_code,503)

    def test_database_failure_is_sanitized_and_releases_lock(self):
        app=FastAPI();app.include_router(router)
        from threading import Lock
        store=Mock();store.lock=Lock();store.db.execute.side_effect=sqlite3.OperationalError('TEST ONLY private path/password')
        app.state.travel=Mock(store=store)
        with TestClient(app) as client:
            r=client.get('/health/ready')
            self.assertEqual(r.status_code,503);self.assertEqual(r.json(),{'status':'unavailable'})
            self.assertTrue(store.lock.acquire(blocking=False));store.lock.release()
            self.assertEqual(client.get('/health/live').status_code,200)

    def test_busy_store_does_not_block_readiness_and_recovers(self):
        from threading import Lock
        app=FastAPI();app.include_router(router)
        store=Mock();store.lock=Lock();app.state.travel=Mock(store=store)
        held=Event();release=Event()
        def hold():
            with store.lock:held.set();release.wait(5)
        thread=Thread(target=hold);thread.start();self.assertTrue(held.wait(2))
        try:
            with TestClient(app) as client:
                self.assertEqual(client.get('/health/ready').status_code,503)
                store.db.execute.assert_not_called()
                release.set();thread.join(2)
                self.assertEqual(client.get('/health/ready').status_code,200)
        finally:release.set();thread.join(2)


if __name__=='__main__':unittest.main()
