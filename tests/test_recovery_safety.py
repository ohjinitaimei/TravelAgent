"""Ensure the explicit recovery seeder refuses real locations and overwrites."""
from pathlib import Path
from copy import deepcopy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name).resolve();self.source=self.root/'source'
        (self.source/'backend').mkdir(parents=True);(self.source/'backend/main.py').write_text('# TEST ONLY guard marker')

    def invoke(self,source,db,phase):
        return subprocess.run([sys.executable,str(ROOT/'tests/recovery_seed.py'),'--test-fixtures-only',
            '--source',str(source),'--db',str(db),'--phase',phase],capture_output=True,timeout=10)

    def test_workspace_business_database_path_is_rejected_before_creation(self):
        # No file is created/read outside this test directory; validation must fail first.
        r=self.invoke(self.source,ROOT/'backend/data/not-a-real-recovery-target.sqlite3','initial')
        self.assertEqual(r.returncode,2)
        self.assertIn(b'Only extracted TEST ONLY',r.stderr)

    def test_initial_phase_never_overwrites_an_existing_test_database(self):
        target=self.root/'exists.sqlite3';target.write_bytes(b'TEST ONLY do not overwrite')
        r=self.invoke(self.source,target,'initial')
        self.assertEqual(r.returncode,2);self.assertEqual(target.read_bytes(),b'TEST ONLY do not overwrite')

    def test_missing_test_database_and_non_extracted_sources_are_rejected(self):
        target=self.root/'missing.sqlite3'
        self.assertEqual(self.invoke(self.source,target,'pending').returncode,2)
        self.assertEqual(self.invoke(ROOT,target,'initial').returncode,2)
        self.assertFalse(target.exists())


class RecoveryRoundtripTests(unittest.TestCase):
    """Current A/B saved records survive snapshots without a model/network service."""
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name).resolve();self.source=self.root/'source';self.db=self.root/'live.sqlite3'
        shutil.copytree(ROOT/'backend',self.source/'backend',ignore=shutil.ignore_patterns('.env','data','__pycache__','*.pyc'))
        for directory,names in (('tests',('test_poi_comparison.py','test_journey_endpoints.py','test_travel.py')),
            ('scripts',('verify_live_quality.py',))):
            (self.source/directory).mkdir(parents=True)
            for name in names:shutil.copyfile(ROOT/directory/name,self.source/directory/name)
        sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]

    def seed(self,phase):
        env=dict(os.environ,TRAVEL_AUTH_MODE='session',TRAVEL_COOKIE_SECURE='0',TRAVEL_SESSION_TTL='28800',
            TRAVEL_SESSION_IDLE_TTL='1800',TRAVEL_CORS_ORIGINS='http://localhost:5173',TRAVEL_AGENT_ENABLED='0',LLM_INTENT_DISABLE_LLM='1')
        for key in ('AMAP_KEY','AMAP_WEB_KEY','AMAP_JS_KEY','AMAP_JS_SECURITY_CODE','DASHSCOPE_API_KEY','OPENAI_API_KEY','TRAVEL_LLM_API_KEY'):
            env[key]=''
        result=subprocess.run([sys.executable,str(ROOT/'tests/recovery_seed.py'),'--test-fixtures-only',
            '--source',str(self.source),'--db',str(self.db),'--phase',phase],capture_output=True,text=True,encoding='utf-8',env=env,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def records(self,store,identifiers):
        result={}
        for name,owner in identifiers.items():
            user=store.db.execute('SELECT id FROM auth_users WHERE username=?',('test-'+name,)).fetchone()[0]
            result[name]={'itineraries':{identifier:store.itinerary(identifier,owner_id=user).model_dump(mode='json') for identifier in owner['itinerary_ids']},
                'draft':store.draft(owner['draft_id'],owner_id=user).model_dump(mode='json'),
                'receipts':{key:store.submission(key,owner_id=user).model_dump(mode='json') for key in owner['receipt_keys']}}
        result['request_snapshots']=store.db.execute('SELECT task_id,data FROM task_requests ORDER BY task_id').fetchall()
        result['receipt_bindings']=store.db.execute('SELECT owner_id,key,fingerprint,task_id FROM user_submissions ORDER BY owner_id,key').fetchall()
        return result

    def test_current_saved_comparison_partial_draft_history_and_receipts_roundtrip_both_snapshots(self):
        from travel.backup import create_snapshot,restore_snapshot,verify_snapshot
        from travel.store import Store
        from verify_recovery import same_records
        identifiers=self.seed('initial')['owners'];self.seed('pending')
        original=Store(self.db)
        try:
            first_records=self.records(original,identifiers)
            for name,owner in identifiers.items():
                saved=first_records[name];comparison=saved['itineraries'][owner['parent_id']]['planning_comparison']
                self.assertTrue(comparison['applied']);self.assertEqual((comparison['baseline']['travel_minutes'],comparison['result']['travel_minutes']),(100,10))
                self.assertTrue(comparison['baseline_days'][0]['stops'][0]['poi']['source']['retrieved_at'])
                self.assertEqual(saved['itineraries'][owner['child_id']]['parent_id'],owner['parent_id'])
                self.assertEqual(saved['draft']['revision'],3);self.assertEqual(len(saved['draft']['clarifications']),2)
                self.assertIsNone(saved['draft']['proposal']['values']['day_schedules'][0]['day_end'])
                self.assertEqual(set(saved['draft']['field_sources'].values()),{'model_extracted','user_input'})
            first=self.root/'first';create_snapshot(self.db,first)
            self.seed('mutate');latest_records=self.records(original,identifiers)
            self.assertNotEqual(latest_records,first_records)
            latest=self.root/'latest';create_snapshot(self.db,latest)
            for label,snapshot,expected in (('first',first,first_records),('latest',latest,latest_records)):
                restored_path=self.root/(label+'-restored.sqlite3');restore_snapshot(snapshot,restored_path)
                restored=Store(restored_path)
                try:
                    same_records(self.records(restored,identifiers),expected)
                    pending=restored.task('test-only-interrupted')
                    self.assertEqual(pending.status,'failed');self.assertEqual(pending.error.code,'backup_restored');self.assertTrue(pending.retry_available)
                finally:restored.close()
                verify_snapshot(snapshot)
            self.assertEqual(original.task('test-only-interrupted').status,'running')
            same_records(self.records(original,identifiers),latest_records)
        finally:original.close()

    def test_record_comparison_rejects_loss_of_comparison_sources_draft_history_or_receipts(self):
        from verify_recovery import same_records
        expected={'itineraries':{'TEST ONLY':{'planning_comparison':{'baseline_days':[{'source':{'provider':'user_input'}}]}}},
            'draft':{'revision':3,'clarifications':[{'values':{'day_schedules':[{'day_start':'09:00','day_end':None}]}}]},
            'receipts':{'TEST ONLY':{'id':'TEST ONLY','status':'succeeded'}}}
        for section in ('itineraries','draft','receipts'):
            altered=deepcopy(expected);altered[section]={}
            with self.subTest(section=section),self.assertRaisesRegex(AssertionError,'Complete A/B'):same_records(altered,expected)
        same_records(deepcopy(expected),expected)


if __name__=='__main__':unittest.main()
