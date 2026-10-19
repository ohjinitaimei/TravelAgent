"""Admission/resource tests with isolated SQLite and explicit TEST ONLY tools."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi.testclient import TestClient
from travel.limits import BusinessLimits
from travel.provider import TravelFailure
from travel.schemas import Task
from travel.store import Store
from travel.tasks import TaskManager
from travel.tools import TravelTools
from test_travel import FixtureProvider, PAYLOAD, stalled_worker


class LimitsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'test.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.store.close)

    def test_quota_survives_restart_expires_and_does_not_charge_partial_buckets(self):
        with patch.dict(os.environ, {'TRAVEL_LIMIT_TOOLS': '1', 'TRAVEL_LIMIT_TOOLS_GLOBAL': '2'}):
            clock = [1000.0]
            limits = BusinessLimits(self.store, clock=lambda: clock[0])
            with limits.tool('alpha'): pass
            with self.assertRaises(TravelFailure) as error:
                with limits.tool('alpha'): pass
            self.assertEqual(error.exception.retry_after, 60)
            # Alpha's rejection must not consume the global slot reserved for beta.
            with limits.tool('beta'): pass
            with closing_store(self.path) as reopened:
                persisted = BusinessLimits(reopened, clock=lambda: clock[0])
                with self.assertRaises(TravelFailure):
                    with persisted.tool('gamma'): pass
                clock[0] += 61
                with persisted.tool('alpha'): pass

    def test_tool_concurrency_is_nonblocking_and_releases_after_failure(self):
        with patch.dict(os.environ, {'TRAVEL_TOOL_CONCURRENCY': '1'}):
            limits = BusinessLimits(self.store)
            started, finish = Event(), Event()

            def running():
                with limits.tool('alpha'):
                    started.set()
                    if not finish.wait(5): raise RuntimeError('TEST ONLY timeout')
                    raise RuntimeError('TEST ONLY failure')

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(running)
                try:
                    self.assertTrue(started.wait(5))
                    with self.assertRaises(TravelFailure) as error:
                        with limits.tool('beta'): pass
                    self.assertEqual(error.exception.code, 'tool_busy')
                finally:
                    finish.set()
                with self.assertRaisesRegex(RuntimeError, 'TEST ONLY failure'): future.result()
            with limits.tool('beta'): pass

    def test_handshake_quota_and_stream_release_are_scoped_and_bounded(self):
        with patch.dict(os.environ, {'TRAVEL_LIMIT_TOOL_CHECKS': '1', 'TRAVEL_LIMIT_STREAMS': '1', 'TRAVEL_LIMIT_STREAMS_GLOBAL': '2'}):
            limits = BusinessLimits(self.store)
            with limits.tool('alpha', check=True): pass
            with self.assertRaises(TravelFailure):
                with limits.tool('alpha', check=True): pass
            with limits.tool('alpha'): pass
            with limits.tool('beta', check=True): pass
            release = limits.acquire_stream('alpha')
            with self.assertRaises(TravelFailure): limits.acquire_stream('alpha')
            beta = limits.acquire_stream('beta')
            with self.assertRaises(TravelFailure): limits.acquire_stream('gamma')
            release(); release()
            gamma = limits.acquire_stream('gamma')
            beta(); gamma()
            self.assertEqual(limits.streams, {})

    def test_invalid_limit_configuration_fails_closed(self):
        for value in ('0', '-1', 'oops', '10001'):
            with patch.dict(os.environ, {'TRAVEL_LIMIT_TASKS': value}), self.assertRaises(ValueError):
                BusinessLimits(self.store)

    def test_rest_tools_share_quota_without_blocking_reads_or_controls(self):
        from main import app

        @contextmanager
        def fixture_tools():
            yield TravelTools(FixtureProvider())

        env = {'TRAVEL_DB_PATH': str(self.path), 'TRAVEL_AUTH_MODE': 'local', 'TRAVEL_LIMIT_TOOLS': '2', 'TRAVEL_LIMIT_TASKS': '1'}
        with patch.dict(os.environ, env), patch('travel.api.open_tools', fixture_tools), TestClient(app) as client:
            base = '/api/v1/travel'
            self.assertEqual(client.get(base + '/pois', params={'keyword': 'TEST ONLY', 'city': 'TEST ONLY'}).status_code, 200)
            self.assertEqual(client.get(base + '/pois/fixture-a').status_code, 200)
            query = {'origin': {'longitude': 116.1, 'latitude': 39.9}, 'destination': {'longitude': 116.2, 'latitude': 39.9}}
            with patch('travel.api.open_tools') as unused:
                rejected = client.post(base + '/routes', json=query)
                self.assertEqual(rejected.status_code, 429, rejected.text)
                self.assertGreater(int(rejected.headers['Retry-After']), 0)
                self.assertEqual(rejected.json()['error']['code'], 'tool_rate_limited')
                unused.assert_not_called()
            # Malformed requests and absent foreign resources never create a task or charge quota.
            self.assertEqual(client.post(base + '/tasks', json={}).status_code, 422)
            self.assertEqual(client.post(base + '/itineraries/missing/adjust', json={'poi_ids_by_day': [['fixture-a']]}).status_code, 404)
            self.assertEqual(app.state.travel.store.tasks(), [])
            terminal = Task(id='test-only-terminal', status='cancelled')
            app.state.travel.store.put_task(terminal)
            self.assertEqual(client.get(base + '/tasks/' + terminal.id).status_code, 200)
            self.assertEqual(client.get(base + '/tasks/' + terminal.id + '/events').status_code, 200)
            self.assertIn('event: terminal', client.get(base + '/tasks/' + terminal.id + '/events/stream').text)
            self.assertEqual(app.state.travel.limits.streams, {})
            self.assertEqual(client.post(base + '/tasks/' + terminal.id + '/cancel').status_code, 200)
            self.assertEqual(client.get(base + '/itineraries').status_code, 200)
            self.assertEqual(client.post(base + '/auth/logout').status_code, 200)
            self.assertEqual(client.get(base + '/capabilities').status_code, 200)

    def test_authenticated_task_quota_uses_server_identity_and_keeps_cancel_available(self):
        from main import app
        env = {'TRAVEL_DB_PATH': str(self.path), 'TRAVEL_AUTH_MODE': 'session', 'TRAVEL_COOKIE_SECURE': '0', 'TRAVEL_LIMIT_TASKS': '1'}
        with patch.dict(os.environ, env), patch('travel.tasks.run', stalled_worker), TestClient(app) as client:
            base = '/api/v1/travel'
            auth = app.state.auth
            headers = []
            for name in ('test-alpha', 'test-beta'):
                auth.create_user(name, 'TEST ONLY admission password 2026')
                identity = auth.login(name, 'TEST ONLY admission password 2026', 'TEST ONLY peer')
                headers.append({'Authorization': 'Bearer ' + identity.token})
            key = {'Idempotency-Key': 'test-only-receipt'}
            first = client.post(base + '/tasks', json=PAYLOAD, headers={**headers[0], **key})
            self.assertEqual(first.status_code, 202, first.text)
            identifier = first.json()['id']
            self.assertEqual(client.post(base + '/tasks', json=PAYLOAD, headers={**headers[0], **key}).json()['id'], identifier)
            rejected = client.post(base + '/tasks', json=PAYLOAD, headers=headers[0])
            self.assertEqual(rejected.status_code, 429, rejected.text)
            self.assertEqual(rejected.json()['error']['code'], 'task_rate_limited')
            self.assertGreater(int(rejected.headers['Retry-After']), 0)
            second = client.post(base + '/tasks', json=PAYLOAD, headers={**headers[1], **key})
            self.assertEqual(second.status_code, 202, second.text)
            self.assertNotEqual(second.json()['id'], identifier)
            self.assertEqual(client.get(base + '/tasks/' + identifier, headers=headers[1]).status_code, 404)
            self.assertEqual(client.post(base + '/tasks/' + identifier + '/cancel', headers=headers[0]).status_code, 200)
            self.assertEqual(client.get(base + '/tasks/' + identifier, headers=headers[0]).json()['status'], 'cancelled')
            self.assertEqual(client.post(base + '/auth/logout', headers=headers[0]).status_code, 200)


@contextmanager
def closing_store(path):
    store = Store(path)
    try: yield store
    finally: store.close()


class TaskLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_dedup_and_owner_quota_cover_all_task_kinds_and_retries(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder, patch.dict(os.environ, {'TRAVEL_LIMIT_TASKS': '1'}):
            store = Store(Path(folder) / 'test.sqlite3')
            manager = TaskManager(store)

            async def pause(*_): await asyncio.Future()

            try:
                with patch.object(manager, 'execute', side_effect=pause):
                    first = manager.create({'request': PAYLOAD}, 'test-only-first', owner_id='alpha')
                    self.assertEqual(manager.create({'request': PAYLOAD}, 'test-only-first', owner_id='alpha').id, first.id)
                    with self.assertRaises(TravelFailure) as conflict:
                        manager.create({'request': {**PAYLOAD, 'budget': 10}}, 'test-only-first', owner_id='alpha')
                    self.assertEqual(conflict.exception.status, 409)
                    manager.cancel(first.id)
                    for payload in ({'kind': 'draft', 'request': {}}, {'request': PAYLOAD, 'parent_id': 'TEST ONLY'}):
                        with self.assertRaises(TravelFailure) as error: manager.create(payload, owner_id='alpha')
                        self.assertEqual(error.exception.code, 'task_rate_limited')
                    with self.assertRaises(TravelFailure): manager.retry(first.id, owner_id='alpha')
                    other = manager.create({'request': PAYLOAD}, 'test-only-first', owner_id='beta')
                    self.assertNotEqual(first.id, other.id)
                    self.assertEqual(len(store.tasks()), 2)
                    self.assertIsNone(store.submission('never-accepted', owner_id='alpha'))
            finally:
                await manager.close(); store.close()

    async def test_active_owner_limit_releases_and_receipts_bypass_full_queue(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder, patch.dict(os.environ, {'TRAVEL_LIMIT_ACTIVE_TASKS': '1'}):
            store = Store(Path(folder) / 'test.sqlite3')
            manager = TaskManager(store, capacity=2)

            async def pause(*_): await asyncio.Future()

            try:
                with patch.object(manager, 'execute', side_effect=pause):
                    first = manager.create({'request': PAYLOAD}, 'test-only-first', owner_id='alpha')
                    with self.assertRaises(TravelFailure) as error: manager.create({'request': PAYLOAD}, owner_id='alpha')
                    self.assertEqual(error.exception.code, 'task_concurrency_limited')
                    manager.create({'request': PAYLOAD}, owner_id='beta')
                    self.assertEqual(manager.create({'request': PAYLOAD}, 'test-only-first', owner_id='alpha').id, first.id)
                    with self.assertRaises(TravelFailure) as error: manager.create({'request': PAYLOAD}, owner_id='gamma')
                    self.assertEqual(error.exception.code, 'queue_full')
                    manager.cancel(first.id)
                    await asyncio.sleep(.01)
                    second = manager.create({'request': PAYLOAD}, owner_id='alpha')
                    self.assertNotEqual(first.id, second.id)
                    self.assertEqual(store.db.execute("SELECT count FROM business_limits WHERE scope='tasks' AND subject='alpha'").fetchone()[0], 2)
            finally:
                await manager.close(); store.close()


if __name__ == '__main__':
    (ROOT / '.tmp').mkdir(exist_ok=True)
    unittest.main()
