"""TEST ONLY serialized rotation and recovery; no production database or timer."""
import json
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from travel.auth import AuthService
from travel.backup import restore_snapshot, verify_snapshot
from travel.backup_schedule import managed, run_backup
from travel.schemas import Task
from travel.store import Store


class ScheduledBackupTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name).resolve();self.path=self.root/'live.sqlite3';self.backups=self.root/'backups'
        self.store=Store(self.path);self.addCleanup(self.store.close)
        with patch.dict(os.environ,{'TRAVEL_AUTH_MODE':'local'}):AuthService(self.store)
        self.store.register_task(Task(id='TEST-ONLY-pending',status='running'),{'request':{'city':'TEST ONLY'}},'TEST-ONLY-RECEIPT','TEST ONLY')
        self.store.event('TEST-ONLY-pending','running','TEST ONLY')

    def test_default_retention_reports_without_deleting_and_explicit_prune_keeps_newest(self):
        first=run_backup(self.path,self.backups,keep=1)
        second=run_backup(self.path,self.backups,keep=1)
        self.assertEqual(second['eligible'],1);self.assertEqual(second['removed'],0)
        self.assertTrue((self.backups/first['created']).exists())
        third=run_backup(self.path,self.backups,keep=2,prune=True)
        self.assertEqual(third['removed'],1)
        self.assertFalse((self.backups/first['created']).exists())
        self.assertEqual(len(managed(self.backups)[0]),2)

    def test_failed_new_snapshot_preserves_previous_backups_and_releases_lock(self):
        first=run_backup(self.path,self.backups)
        with patch('travel.backup_schedule.create_snapshot',side_effect=TimeoutError('TEST ONLY')):
            with self.assertRaises(TimeoutError):run_backup(self.path,self.backups,keep=1,prune=True)
        verify_snapshot(self.backups/first['created'])
        self.assertFalse((self.backups/'.backup.lock').exists())

    def test_manual_corrupt_incomplete_and_extra_file_directories_are_never_pruned(self):
        first=run_backup(self.path,self.backups)
        first_path=self.backups/first['created'];(first_path/'operator-note.txt').write_text('TEST ONLY keep')
        corrupt=run_backup(self.path,self.backups)
        corrupt_path=self.backups/corrupt['created'];(corrupt_path/'snapshot.sqlite3').write_bytes(b'TEST ONLY corrupt')
        manual=self.backups/'manual';manual.mkdir();(manual/'keep.txt').write_text('TEST ONLY')
        result=run_backup(self.path,self.backups,keep=1,prune=True)
        self.assertEqual(result['removed'],0);self.assertEqual(result['skipped'],3)
        self.assertTrue(first_path.exists());self.assertTrue(corrupt_path.exists());self.assertTrue(manual.exists())

    def test_exclusive_lock_is_not_stolen_and_source_inside_backup_root_is_rejected(self):
        run_backup(self.path,self.backups)
        lock=self.backups/'.backup.lock';lock.write_text('TEST ONLY another process')
        with self.assertRaises(FileExistsError):run_backup(self.path,self.backups)
        self.assertEqual(lock.read_text(),'TEST ONLY another process')
        with self.assertRaises(ValueError):run_backup(self.path,self.root,prune=True)

    def test_rotation_snapshot_restores_without_overwriting_source(self):
        result=run_backup(self.path,self.backups,keep=1,prune=True)
        destination=self.root/'restored.sqlite3'
        restored=restore_snapshot(self.backups/result['created'],destination)
        self.assertEqual(restored['interrupted_tasks'],1)
        with closing(sqlite3.connect(destination)) as db:
            task=json.loads(db.execute('SELECT data FROM tasks').fetchone()[0])
            self.assertEqual(task['error']['code'],'backup_restored');self.assertTrue(task['retry_available'])
        self.assertEqual(self.store.task('TEST-ONLY-pending').status,'running')
        with self.assertRaises(FileExistsError):restore_snapshot(self.backups/result['created'],destination)

    def test_cli_uses_explicit_database_and_preserves_source_connection(self):
        env={**os.environ,'PYTHONIOENCODING':'utf-8'}
        r=subprocess.run([sys.executable,'-m','travel.backup_schedule','--db',str(self.path),'--root',str(self.backups),'--keep','1'],
            cwd=ROOT/'backend',env=env,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['verified'])
        self.assertTrue(self.store.task('TEST-ONLY-pending'))

    def test_invalid_keep_and_missing_source_do_not_create_snapshots(self):
        for keep in (0,366,True):
            with self.assertRaises(ValueError):run_backup(self.path,self.backups,keep)
        with self.assertRaises(ValueError):run_backup(self.root/'missing.sqlite3',self.backups)
        self.assertFalse(self.backups.exists())

    def test_current_verified_snapshot_is_kept_after_clock_moves_backwards(self):
        previous=run_backup(self.path,self.backups)
        with patch('travel.backup_schedule.datetime') as clock:
            clock.now.return_value=datetime(2000,1,1,tzinfo=timezone.utc)
            current=run_backup(self.path,self.backups,keep=1,prune=True)
        self.assertTrue((self.backups/current['created']).exists())
        self.assertFalse((self.backups/previous['created']).exists())
        verify_snapshot(self.backups/current['created'])


if __name__=='__main__':unittest.main()
