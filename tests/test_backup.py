"""WAL/restore drills using TEST ONLY accounts and business records."""
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi.testclient import TestClient
from travel.auth import AuthService, password_hash, token_hash
from travel.backup import checksum, create_snapshot, restore_snapshot, verify_snapshot
from travel.limits import BusinessLimits
from travel.planner import plan
from travel.schemas import Draft, DraftRequest, DraftSubmission, DraftValues, PlanRequest, Task
from travel.store import Store
from test_travel import FixtureProvider, PAYLOAD

PASSWORD = 'TEST ONLY backup password 2026'


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.digest = password_hash(PASSWORD)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'live.sqlite3'
        self.snapshot = self.root / 'backups' / 'test-only'
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        with patch.dict(os.environ, {'TRAVEL_AUTH_MODE': 'local'}): AuthService(self.store)
        self.limits = BusinessLimits(self.store)
        with self.store.db:
            self.store.db.executemany('INSERT INTO auth_users VALUES (?,?,?,0)', [
                ('alpha-id', 'test-alpha', self.digest), ('beta-id', 'test-beta', self.digest)])
        self.trips = []
        for owner in ('alpha-id', 'beta-id'):
            task = Task(id='test-only-' + owner, status='queued')
            self.store.register_task(task, {'request': PAYLOAD}, 'test-only-key', 'TEST ONLY fingerprint', owner_id=owner)
            trip = plan(PlanRequest.model_validate(PAYLOAD), lambda *_: None, provider=FixtureProvider())
            self.store.succeed(task, trip)
            self.trips.append(trip)
        task = Task(id='test-only-draft-task', kind='draft', status='queued')
        self.store.register_task(task, {'kind': 'draft', 'request': {}}, None, '', owner_id='alpha-id')
        draft = Draft(id='test-only-draft', input=DraftRequest(text='TEST ONLY', reference_date='2026-10-19'),
                      proposal=DraftSubmission(values=DraftValues(city='TEST ONLY'), evidence={}),
                      questions=[], warnings=[], coordinator_action='ask_clarification', revision=3)
        self.store.succeed_draft(task, draft)
        pending = Task(id='test-only-pending', status='running')
        self.store.register_task(pending, {'request': PAYLOAD}, 'test-only-pending', 'TEST ONLY', owner_id='beta-id')
        self.store.event(pending.id, 'running', 'TEST ONLY')
        self.old_token = secrets.token_urlsafe(32)
        with self.store.db:
            current = time.time()
            self.store.db.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)', (token_hash(self.old_token), 'alpha-id', current + 3600, current))
        with self.limits.tool('alpha-id'): pass

    def test_live_wal_snapshot_and_restored_api_preserve_ownership_and_revoke_sessions(self):
        # Keep a live WAL connection with an uncommitted change while backing up.
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute("UPDATE auth_users SET username='not-committed' WHERE id='alpha-id'")
            create_snapshot(self.path, self.snapshot)
            writer.rollback()
        info = verify_snapshot(self.snapshot)
        self.assertEqual(info['rows']['itineraries'], 2)
        self.assertEqual(info['rows']['auth_sessions'], 1)
        self.assertNotIn(self.old_token, (self.snapshot / 'manifest.json').read_text())
        destination = self.root / 'recovered.sqlite3'
        self.assertEqual(restore_snapshot(self.snapshot, destination), {'interrupted_tasks': 1, 'sessions_revoked': 1})
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT count FROM business_limits WHERE scope='tools' AND subject='alpha-id'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT username FROM auth_users WHERE id='alpha-id'").fetchone()[0], 'test-alpha')
        from main import app
        env = {'TRAVEL_DB_PATH': str(destination), 'TRAVEL_AUTH_MODE': 'session', 'TRAVEL_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), TestClient(app) as client:
            base = '/api/v1/travel'
            self.assertEqual(client.get(base + '/itineraries', headers={'Authorization': 'Bearer ' + self.old_token}).status_code, 401)
            headers = []
            for name in ('test-alpha', 'test-beta'):
                login = client.post(base + '/auth/login', json={'username': name, 'password': PASSWORD, 'transport': 'bearer'})
                self.assertEqual(login.status_code, 200, login.text)
                headers.append({'Authorization': 'Bearer ' + login.json()['access_token']})
            for own, foreign, trip in [(headers[0], headers[1], self.trips[0]), (headers[1], headers[0], self.trips[1])]:
                self.assertEqual(client.get(base + '/itineraries/' + trip.id, headers=own).status_code, 200)
                self.assertEqual(client.get(base + '/itineraries/' + trip.id, headers=foreign).status_code, 404)
            self.assertEqual(client.get(base + '/drafts/test-only-draft', headers=headers[0]).json()['revision'], 3)
            receipt = client.get(base + '/submissions/test-only-pending', headers=headers[1]).json()
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['error']['code'], 'backup_restored')
            self.assertTrue(receipt['retry_available'])
            self.assertEqual(app.state.travel.store.task_request(receipt['id']), {'request': PAYLOAD})
        # Neither the source nor the snapshot was mutated by recovery.
        self.assertEqual(self.store.task('test-only-pending').status, 'running')
        verify_snapshot(self.snapshot)

    def test_corrupt_or_incomplete_snapshot_never_publishes_a_destination(self):
        create_snapshot(self.path, self.snapshot)
        target = self.root / 'recovered.sqlite3'
        with (self.snapshot / 'snapshot.sqlite3').open('ab') as stream: stream.write(b'TEST ONLY corruption')
        with self.assertRaises(ValueError): restore_snapshot(self.snapshot, target)
        self.assertFalse(target.exists())
        (self.snapshot / 'manifest.json').unlink()
        with self.assertRaises(ValueError): verify_snapshot(self.snapshot)

    def test_missing_ownership_and_cross_user_receipts_fail_even_with_updated_checksum(self):
        create_snapshot(self.path, self.snapshot)
        database = self.snapshot / 'snapshot.sqlite3'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE user_submissions SET owner_id='beta-id',key='test-only-forged' WHERE owner_id='alpha-id'")
        info = json.loads((self.snapshot / 'manifest.json').read_text())
        info.update(sha256=checksum(database), size_bytes=database.stat().st_size)
        (self.snapshot / 'manifest.json').write_text(json.dumps(info))
        with self.assertRaisesRegex(ValueError, '归属'): verify_snapshot(self.snapshot)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DELETE FROM resource_owners WHERE kind='draft'")
        info.update(sha256=checksum(database), size_bytes=database.stat().st_size)
        (self.snapshot / 'manifest.json').write_text(json.dumps(info))
        with self.assertRaisesRegex(ValueError, '归属'): verify_snapshot(self.snapshot)

    def test_targets_and_sidecars_are_never_overwritten(self):
        create_snapshot(self.path, self.snapshot)
        original = checksum(self.path)
        with self.assertRaises(FileExistsError): restore_snapshot(self.snapshot, self.path)
        self.assertEqual(checksum(self.path), original)
        manifest = (self.snapshot / 'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError): create_snapshot(self.path, self.snapshot)
        self.assertEqual((self.snapshot / 'manifest.json').read_bytes(), manifest)
        for suffix in ('-wal', '-shm', '-journal'):
            target = self.root / ('test-only-sidecar' + suffix + '.sqlite3')
            sidecar = Path(str(target) + suffix)
            sidecar.write_bytes(b'TEST ONLY')
            with self.assertRaises(FileExistsError): restore_snapshot(self.snapshot, target)
            self.assertFalse(target.exists())
            self.assertEqual(sidecar.read_bytes(), b'TEST ONLY')

    def test_missing_source_or_incompatible_schema_is_rejected(self):
        with self.assertRaises(ValueError): create_snapshot(self.root / 'missing.sqlite3', self.snapshot)
        self.assertFalse(self.snapshot.exists())
        old = self.root / 'old.sqlite3'
        with closing(sqlite3.connect(old)) as db: db.execute('CREATE TABLE tasks (id TEXT)')
        with self.assertRaises(ValueError): create_snapshot(old, self.snapshot)
        self.assertFalse(self.snapshot.exists())

    def test_cli_restore_requires_explicit_offline_flag(self):
        create_snapshot(self.path, self.snapshot)
        target = self.root / 'cli.sqlite3'
        result = subprocess.run([sys.executable, '-m', 'travel.backup', 'restore', str(self.snapshot), '--db', str(target)],
                                cwd=ROOT / 'backend', capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'--service-stopped', result.stderr)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    (ROOT / '.tmp').mkdir(exist_ok=True)
    unittest.main()
