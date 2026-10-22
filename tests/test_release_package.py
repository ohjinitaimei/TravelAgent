"""TEST ONLY Git repo and Web fixture; no production artifacts or real credentials."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from package_release import build_release, normalized, source_allowed, verify_archive


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(self.folder.cleanup)
        self.base=Path(self.folder.name).resolve();self.repo=self.base/'repo';self.repo.mkdir()
        self.web=self.base/'dist';(self.web/'assets').mkdir(parents=True)
        (self.web/'index.html').write_text('<html>TEST ONLY production-shaped fixture</html>')
        (self.web/'assets/app.js').write_text('// TEST ONLY compiled fixture')
        self.files={'.gitignore':b'.env\nnode_modules/\n','README.md':b'TEST ONLY\r\n','.env.example':b'TEST_ONLY_KEY=\n'}
        for name,content in self.files.items():(self.repo/name).write_bytes(content)
        entries=[{'path':name,'bytes':len(normalized(content)),'sha256':hashlib.sha256(normalized(content)).hexdigest()} for name,content in sorted(self.files.items())]
        (self.repo/'PUBLISH_MANIFEST.json').write_text(json.dumps({'format_version':1,'purpose':'source_inventory','files':entries}))
        for args in [('init','-q'),('add','.'),('-c','user.name=TEST ONLY','-c','user.email=test@example.invalid','commit','-qm','TEST ONLY')]:
            subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True)
        self.private=self.repo/'.env';self.private.write_text('AMAP_WEB_KEY=TEST_ONLY_SERVER_PRIVATE_VALUE\n')

    def build(self,name='release'):
        return build_release(self.base/name,self.web,self.private,root=self.repo)

    def test_reproducible_normalized_archive_excludes_runtime_files(self):
        first=self.build();second=self.build('second')
        self.assertEqual(first['sha256'],second['sha256']);self.assertFalse(first['working_tree_dirty'])
        metadata=verify_archive(Path(first['archive']))
        with zipfile.ZipFile(first['archive']) as archive:
            self.assertEqual(archive.read('source/README.md'),b'TEST ONLY\n')
            self.assertNotIn('source/.env',archive.namelist());self.assertNotIn('source/.git/config',archive.namelist())
        self.assertEqual(len(metadata['files']),6)

    def test_changed_source_refuses_to_create_release(self):
        (self.repo/'README.md').write_text('TEST ONLY changed')
        with self.assertRaises(ValueError):self.build()
        self.assertFalse((self.base/'release').exists())

    def test_private_credentials_in_web_abort_before_publication(self):
        (self.web/'assets/app.js').write_text('TEST_ONLY_SERVER_PRIVATE_VALUE')
        with self.assertRaises(ValueError):self.build()
        self.assertFalse((self.base/'release').exists())

    def test_existing_output_is_preserved(self):
        self.build();before=(self.base/'release/TravelAgent.zip').read_bytes()
        with self.assertRaises(FileExistsError):self.build()
        self.assertEqual((self.base/'release/TravelAgent.zip').read_bytes(),before)

    def test_corrupt_payload_is_rejected_by_independent_verifier(self):
        result=self.build();bad=self.base/'bad.zip'
        with zipfile.ZipFile(result['archive']) as src,zipfile.ZipFile(bad,'w') as dst:
            for name in src.namelist():dst.writestr(name,b'TEST ONLY corrupted' if name=='web/assets/app.js' else src.read(name))
        with self.assertRaises(ValueError):verify_archive(bad)

    def test_dangerous_paths_and_unexpected_members_are_rejected(self):
        for name in ['../secret','/secret','a/../secret','a\\secret','C:/secret','.env','backend/data/live.db','backend/pois.json','deploy/backend.env',
                     'android/release.jks','android/release.keystore','android/key.properties','backend/id_rsa','backend/id_ed25519','deploy/service.ppk']:
            self.assertFalse(source_allowed(name),name)
        self.assertTrue(source_allowed('deploy/backend.env.example'))
        result=self.build();bad=self.base/'unexpected.zip'
        with zipfile.ZipFile(result['archive']) as src,zipfile.ZipFile(bad,'w') as dst:
            for name in src.namelist():dst.writestr(name,src.read(name))
            dst.writestr('web/extra.txt','TEST ONLY')
        with self.assertRaises(ValueError):verify_archive(bad)

    def test_verified_default_dist_cannot_attest_another_web_payload(self):
        import package_release
        from verification_context import tree_digest
        record={'context':{'fingerprint':'TEST ONLY'},'web_build':tree_digest(self.web)}
        manifest=json.loads((self.repo/'PUBLISH_MANIFEST.json').read_text())
        (self.web/'assets/app.js').write_text('// TEST ONLY stale alternate Web')
        with patch.object(package_release,'ROOT',self.repo),patch.object(package_release,'inventory',return_value=manifest),patch('verify_web_build.validate',return_value=record):
            with self.assertRaises(ValueError):self.build()
        self.assertFalse((self.base/'release').exists())

    def test_bound_archive_records_the_verified_web_bytes(self):
        import package_release
        from verification_context import tree_digest
        record={'context':{'fingerprint':'TEST ONLY'},'web_build':tree_digest(self.web)}
        manifest=json.loads((self.repo/'PUBLISH_MANIFEST.json').read_text())
        with patch.object(package_release,'ROOT',self.repo),patch.object(package_release,'inventory',return_value=manifest),patch('verify_web_build.validate',return_value=record):
            result=self.build()
        meta=verify_archive(Path(result['archive']))
        self.assertEqual(meta['verification']['web_fingerprint'],record['web_build']['fingerprint'])


if __name__=='__main__':unittest.main()
