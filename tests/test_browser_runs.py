"""TEST ONLY report data and directories; no browser or network needed."""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from browser_runs import run_id,reserve,case_keys,verify_report
class BrowserRunTests(unittest.TestCase):
    def report(self):return {'errors':[],'stats':{'unexpected':0,'flaky':0,'skipped':0},'suites':[{'specs':[{'id':'TEST ONLY','tests':[{'projectName':'chromium','status':'expected','results':[{'status':'passed','retry':0}]}]}]}]}
    def test_discovery_and_exactly_once_report_match(self):
        report=self.report();keys,_=case_keys(report)
        self.assertEqual(verify_report(report,keys),1)
    def test_reject_missing_extra_skipped_failed_or_retried_cases(self):
        report=self.report();keys,_=case_keys(report)
        with self.assertRaises(ValueError):verify_report(report,keys+['missing'])
        for kind in ('skip','retry','fail','duplicate','empty','error'):
            bad=deepcopy(report);test=bad['suites'][0]['specs'][0]['tests'][0]
            if kind=='skip':test['results'][0]['status']='skipped'
            if kind=='retry':test['results'].append(deepcopy(test['results'][0]))
            if kind=='fail':test['results'][0]['status']='failed'
            if kind=='duplicate':bad['suites'].append(deepcopy(bad['suites'][0]))
            if kind=='empty':bad['suites']=[]
            if kind=='error':bad['errors']=[{'message':'TEST ONLY'}]
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify_report(bad,keys)
    def test_run_id_rejects_paths_and_empty_values(self):
        self.assertNotEqual(run_id(),run_id())
        for value in ('','..','a/b','a\\b','C:drive','a b','x'*65):
            with self.subTest(value=value),self.assertRaises(ValueError):run_id(value)
    def test_overlap_never_reuses_existing_evidence_but_other_runs_are_independent(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            root=Path(folder)
            first=reserve(root,'TEST-ONLY','chromium','local');(first/'proof').write_text('TEST ONLY')
            with self.assertRaises(FileExistsError):reserve(root,'TEST-ONLY','chromium','local')
            self.assertEqual((first/'proof').read_text(),'TEST ONLY')
            self.assertNotEqual(reserve(root,'TEST-ONLY','firefox','local'),first)
            self.assertNotEqual(reserve(root,'TEST-OTHER','chromium','local'),first)
    def test_matrix_requires_all_scopes_full_discovery_and_graceful_shutdown(self):
        import json
        from unittest.mock import patch
        import summarize_browser_runs as matrix
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            root=Path(folder)
            for browser in ['chromium','firefox','webkit']:
                for suite in ['local','auth','resilience']:
                    path=reserve(root,'TEST-MATRIX',browser,suite);report=self.report()
                    report['suites'][0]['specs'][0]['tests'][0]['projectName']=browser
                    planned,_=case_keys(report)
                    meta={'run_id':'TEST-MATRIX','browser':browser,'suite':suite,'complete_suite':True,'passed':True,'services_stopped_gracefully':True,'planned_cases':planned,'passed_count':1}
                    (path/'run.json').write_text(json.dumps(meta),encoding='utf-8');(path/'report.json').write_text(json.dumps(report),encoding='utf-8')
            with patch.object(matrix,'ROOT',root):
                self.assertEqual(matrix.summarize('TEST-MATRIX')['executions'],9)
                meta['services_stopped_gracefully']=False;(path/'run.json').write_text(json.dumps(meta),encoding='utf-8')
                with self.assertRaises(ValueError):matrix.summarize('TEST-MATRIX')
                meta['services_stopped_gracefully']=True;meta['complete_suite']=False;(path/'run.json').write_text(json.dumps(meta),encoding='utf-8')
                with self.assertRaises(ValueError):matrix.summarize('TEST-MATRIX')
if __name__=='__main__':unittest.main()
