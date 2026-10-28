"""TEST ONLY lifecycle failures; no browser, model or production database."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from verify_browser import verification_workspace


class BrowserCleanupTests(unittest.TestCase):
    def test_success_is_written_only_after_actual_cleanup(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            destination=Path(folder);metadata={'passed':False}
            report=destination/'run.json';report.write_text(json.dumps(metadata))
            with verification_workspace(destination,metadata) as work:
                (work/'test-only.txt').write_text('TEST ONLY')
                metadata['passed']=True
                self.assertFalse(json.loads(report.read_text())['passed'])
            result=json.loads(report.read_text())
            self.assertTrue(result['passed']);self.assertTrue(result['cleanup_completed'])
            self.assertFalse(work.exists())

    def test_cleanup_error_cannot_leave_a_passing_report_or_private_error_text(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            destination=Path(folder);work=destination/'remaining';work.mkdir()
            class FailingDirectory:
                name=str(work)
                def __enter__(self):return self.name
                def __exit__(self,*_):raise PermissionError('TEST_ONLY_PRIVATE_PATH')
            metadata={'passed':False}
            with patch('verify_browser.tempfile.TemporaryDirectory',return_value=FailingDirectory()),self.assertRaises(PermissionError):
                with verification_workspace(destination,metadata):metadata['passed']=True
            result=json.loads((destination/'run.json').read_text())
            self.assertFalse(result['passed']);self.assertFalse(result['cleanup_completed'])
            self.assertEqual(result['failure_type'],'PermissionError')
            self.assertNotIn('PRIVATE',json.dumps(result))

    def test_body_failure_stays_failed_even_when_cleanup_succeeds(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            destination=Path(folder);metadata={'passed':True}
            with self.assertRaises(ValueError):
                with verification_workspace(destination,metadata):raise ValueError('TEST ONLY')
            result=json.loads((destination/'run.json').read_text())
            self.assertFalse(result['passed']);self.assertTrue(result['cleanup_completed'])


if __name__=='__main__':unittest.main()
