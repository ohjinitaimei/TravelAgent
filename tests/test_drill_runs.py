"""TEST ONLY local evidence lifecycle; no HTTPS service or external calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from drill_runs import begin,close_service,finish,reserve

CONTEXT={'base_commit':'TEST ONLY base','fingerprint':'TEST ONLY fingerprint','files':[]}


class DrillRunTests(unittest.TestCase):
    def folder(self):
        return tempfile.TemporaryDirectory(dir=ROOT/'.tmp')

    def test_reserved_scopes_never_replace_prior_evidence(self):
        with self.folder() as folder:
            root=Path(folder)
            deployment=reserve(root,'TEST-ONLY','deployment')
            (deployment/'report.json').write_text('TEST ONLY existing evidence',encoding='utf-8')
            with self.assertRaises(FileExistsError):reserve(root,'TEST-ONLY','deployment')
            self.assertEqual((deployment/'report.json').read_text(encoding='utf-8'),'TEST ONLY existing evidence')
            recovery=reserve(root,'TEST-ONLY','recovery')
            self.assertNotEqual(deployment,recovery)
            self.assertNotEqual(reserve(root,None,'deployment').parent,reserve(root,None,'deployment').parent)
            self.assertEqual(deployment.relative_to(root).as_posix(),'artifacts/drill-runs/TEST-ONLY/deployment')

    def test_invalid_scopes_and_ids_cannot_escape_or_reuse_legacy_directory(self):
        with self.folder() as folder:
            root=Path(folder);legacy=root/'artifacts/deployment'
            legacy.mkdir(parents=True);(legacy/'report.json').write_text('TEST ONLY legacy',encoding='utf-8')
            for identifier in ('','..','../legacy','a/b','a\\b','C:drive','a b','x'*65):
                with self.subTest(identifier=identifier),self.assertRaises(ValueError):reserve(root,identifier,'deployment')
            with self.assertRaises(ValueError):reserve(root,'TEST-ONLY','other')
            reserve(root,'TEST-ONLY','deployment')
            self.assertEqual((legacy/'report.json').read_text(encoding='utf-8'),'TEST ONLY legacy')

    def test_success_requires_every_started_service_and_cleanup_and_stable_context(self):
        with self.folder() as folder:
            root=Path(folder)
            good=[{'name':'api','returncode':0,'forced':False},{'name':'gateway','returncode':0,'forced':False}]
            variants=[('normal',good,True,CONTEXT,True),
                ('forced',[good[0],{'name':'gateway','returncode':0,'forced':True}],True,CONTEXT,False),
                ('nonzero',[good[0],{'name':'gateway','returncode':1,'forced':False}],True,CONTEXT,False),
                ('unfinished',[good[0],{'name':'gateway','returncode':None,'forced':False}],True,CONTEXT,False),
                ('cleanup',good,False,CONTEXT,False),('none',[],True,CONTEXT,False),
                ('changed',good,True,{**CONTEXT,'fingerprint':'TEST ONLY changed'},False)]
            for name,services,clean,context,expected in variants:
                with self.subTest(name=name):
                    path=reserve(root,'TEST-'+name,'deployment')
                    started=begin(path,source='TEST ONLY',context=CONTEXT)
                    self.assertEqual(json.loads((path/'run.json').read_text())['status'],'running')
                    self.assertNotIn('completed_at',started)
                    final=finish(path,started,services=services,cleanup_completed=clean,context=context)
                    self.assertEqual(final['passed'],expected)
                    self.assertEqual(final['status'],'passed' if expected else 'failed')
                    self.assertEqual(json.loads((path/'run.json').read_text())['passed'],expected)
                    self.assertEqual(final['context'],CONTEXT)
                    self.assertIn('completed_at',final)

    def test_original_failure_survives_a_successful_shutdown_without_leaking_error_text(self):
        with self.folder() as folder:
            path=reserve(Path(folder),'TEST-FAILURE','deployment')
            metadata=begin(path,source='TEST ONLY',context=CONTEXT)
            error=AssertionError('TEST ONLY private business failure detail')
            final=finish(path,metadata,error=error,services=[{'name':'api','returncode':0,'forced':False}],cleanup_completed=True,context=CONTEXT)
            self.assertFalse(final['passed'])
            self.assertTrue(final['services_stopped_gracefully'])
            self.assertEqual(final['exceptionType'],'AssertionError')
            self.assertNotIn('private business',json.dumps(final))

    def test_forced_service_exit_cannot_be_reported_graceful_even_with_zero_returncode(self):
        process=Mock()
        process.returncode=0
        process.wait.side_effect=[subprocess.TimeoutExpired('TEST ONLY',15),0]
        result=close_service(process,'api')
        self.assertTrue(result['forced'])
        self.assertEqual(result['returncode'],0)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_hung_termination_is_killed_and_remaining_services_can_still_be_checked(self):
        process=Mock();process.returncode=-9
        process.wait.side_effect=[subprocess.TimeoutExpired('TEST ONLY',15),subprocess.TimeoutExpired('TEST ONLY',5),-9]
        result=close_service(process,'api')
        self.assertTrue(result['forced']);self.assertEqual(result['returncode'],-9)
        process.terminate.assert_called_once();process.kill.assert_called_once()
        other=Mock();other.wait.return_value=0;other.returncode=0
        self.assertEqual(close_service(other,'gateway')['returncode'],0)
        other.terminate.assert_not_called()

    def test_deployment_preflight_failure_keeps_terminal_evidence_and_refuses_reuse(self):
        import verify_deployment as deployment
        with self.folder() as folder:
            root=Path(folder)
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'capture',return_value=CONTEXT):
                with self.assertRaisesRegex(ValueError,'Caddy executable not found'):
                    deployment.verify(root/'TEST-ONLY-MISSING-CADDY','TEST-PREFLIGHT')
                report_path=root/'artifacts/drill-runs/TEST-PREFLIGHT/deployment/report.json'
                original=report_path.read_text(encoding='utf-8')
                report=json.loads(original)
                self.assertEqual(report['status'],'failed')
                self.assertEqual(report['exceptionType'],'ValueError')
                self.assertFalse(report['services_stopped_gracefully'])
                self.assertEqual(report['passed'],0)
                self.assertFalse(report['tlsVerification'])
                self.assertIn('completed_at',report)
                with self.assertRaises(FileExistsError):deployment.verify(root/'TEST-ONLY-MISSING-CADDY','TEST-PREFLIGHT')
                self.assertEqual(report_path.read_text(encoding='utf-8'),original)

    def test_build_failure_is_not_hidden_by_cleanup_and_temporary_files_are_removed(self):
        import verify_deployment as deployment
        with self.folder() as folder:
            root=Path(folder);caddy=root/'TEST-ONLY-CADDY';caddy.touch()
            failure=AssertionError('TEST ONLY build failure')
            with patch.object(deployment,'ROOT',root),patch.object(deployment,'capture',return_value=CONTEXT),\
                patch.object(deployment.subprocess,'check_output',return_value='v2.11.7 TEST ONLY'),\
                patch.object(deployment.shutil,'which',return_value='TEST-ONLY-NPM'),\
                patch.object(deployment.subprocess,'run',side_effect=failure),\
                patch.object(deployment.subprocess,'Popen',side_effect=AssertionError('Must not start a service')):
                with self.assertRaises(AssertionError) as result:deployment.verify(caddy,'TEST-BUILD-FAILURE')
            self.assertIs(result.exception,failure)
            self.assertEqual(list((root/'.tmp').iterdir()),[])
            report=json.loads((root/'artifacts/drill-runs/TEST-BUILD-FAILURE/deployment/report.json').read_text())
            self.assertTrue(report['cleanup_completed'])
            self.assertEqual(report['exceptionType'],'AssertionError')
            self.assertEqual(report['status'],'failed')
            self.assertTrue((root/'artifacts/drill-runs/TEST-BUILD-FAILURE/deployment/api.log').is_file())


if __name__=='__main__':unittest.main()
