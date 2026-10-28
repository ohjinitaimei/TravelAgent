"""TEST ONLY acceptance-runner boundaries; never starts a model or travel service."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import verify_live_requirements as live


class LiveRequirementsRunnerTests(unittest.TestCase):
    def test_missing_opt_in_invalid_dates_and_path_escape_never_start_a_service(self):
        valid=['--allow-model-call','--reference-date','2026-10-28','--date','2026-10-30']
        for args in (valid[1:],['--allow-model-call','--reference-date','invalid','--date','2026-10-30'],
                     valid+['--run-id','../escape'],valid+['--scenario','relative-date','relative-date']):
            with self.subTest(args=args),patch.object(live.subprocess,'Popen') as spawn,self.assertRaises(SystemExit):
                live.main(args)
            spawn.assert_not_called()

    def test_existing_evidence_is_preserved_before_service_or_model_start(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            root=Path(folder);output=root/'artifacts/live-requirements-runs/TEST-ONLY-existing'
            output.mkdir(parents=True);report=output/'summary.json';report.write_text('TEST ONLY preserved',encoding='utf-8')
            with patch.object(live,'ROOT',root),patch.object(live.subprocess,'Popen') as spawn,self.assertRaises(FileExistsError):
                live.main(['--allow-model-call','--reference-date','2026-10-28','--date','2026-10-30','--run-id','TEST-ONLY-existing'])
            spawn.assert_not_called()
            self.assertEqual(report.read_text(encoding='utf-8'),'TEST ONLY preserved')

    def test_database_audit_counts_failed_tasks_extra_calls_and_leaves_database_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            path=Path(folder)/'test.sqlite3'
            db=sqlite3.connect(path)
            try:
                for table in ('tasks','events','drafts','itineraries'):db.execute(f'CREATE TABLE {table} (data TEXT)')
                for status in ('succeeded','failed','succeeded'):
                    db.execute('INSERT INTO tasks VALUES (?)',(json.dumps({'kind':'draft','status':status}),))
                for _ in range(4):db.execute('INSERT INTO events VALUES (?)',(json.dumps({'stage':'agent_call'}),))
                db.execute('INSERT INTO drafts VALUES (?)',('{}',));db.commit()
            finally:db.close()
            result=live.audit_db(path)
            self.assertEqual(result['task_count'],3)
            self.assertEqual(result['task_statuses'],['succeeded','failed','succeeded'])
            self.assertEqual(result['agent_call_events'],4)
            self.assertEqual(result['draft_count'],1)
            self.assertEqual(result['itinerary_count'],0)
            path.rename(path.with_name('closed.sqlite3'))


if __name__=='__main__':unittest.main()
