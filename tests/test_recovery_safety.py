"""Ensure the explicit recovery seeder refuses real locations and overwrites."""
from pathlib import Path
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


if __name__=='__main__':unittest.main()
