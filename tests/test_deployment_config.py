"""Deployment preflight checks use only temporary TEST ONLY paths/values."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_deployment import origin, validate


class DeploymentConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'.tmp');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name).resolve();self.web=self.root/'dist';(self.web/'assets').mkdir(parents=True)
        (self.web/'index.html').write_text('<html>TEST ONLY</html>')
        self.backend={'TRAVEL_PRODUCTION':'1','TRAVEL_AUTH_MODE':'session','TRAVEL_COOKIE_SECURE':'1',
            'TRAVEL_CORS_ORIGINS':'https://travel.test','TRAVEL_DB_PATH':str(self.root/'test.sqlite3')}
        self.gateway={'TRAVEL_SITE':'https://travel.test','TRAVEL_HTTP_SITE':'http://travel.test',
            'TRAVEL_WEB_ROOT':str(self.web),'TRAVEL_CADDY_DATA':str(self.root/'certificates')}

    def test_valid_configuration_never_creates_database(self):
        validate(self.backend,self.gateway)
        self.assertFalse(Path(self.backend['TRAVEL_DB_PATH']).exists())

    def test_https_identity_and_origin_must_agree(self):
        for key in ['TRAVEL_PRODUCTION','TRAVEL_AUTH_MODE','TRAVEL_COOKIE_SECURE']:
            with self.subTest(key=key),self.assertRaises(ValueError):validate({**self.backend,key:'0'},self.gateway)
        for value in ['http://travel.test','https://user:password@travel.test','https://travel.test/path','https://travel.test?x=1','https://travel.test:0','https://travel.test:bad','https://*.test','https://travel.test\n']:
            with self.subTest(value=value),self.assertRaises(ValueError):origin(value)
        with self.assertRaises(ValueError):validate({**self.backend,'TRAVEL_CORS_ORIGINS':'*'},self.gateway)

    def test_edge_admin_and_api_remain_on_loopback(self):
        for key in ['TRAVEL_UPSTREAM','TRAVEL_CADDY_ADMIN']:
            for value in ['0.0.0.0:8000','127.0.0.1:99999','https://test.invalid']:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate(self.backend,{**self.gateway,key:value})
        with self.assertRaises(ValueError):validate(self.backend,{**self.gateway,'TRAVEL_TLS':'tls internal'})
        with self.assertRaises(ValueError):validate(self.backend,{**self.gateway,'TRAVEL_BIND':'invalid address'})

    def test_database_and_secrets_cannot_be_published(self):
        with self.assertRaises(ValueError):validate({**self.backend,'TRAVEL_DB_PATH':str(self.web/'db.sqlite3')},self.gateway)
        secret='TEST_ONLY_PRIVATE_SERVER_KEY'
        (self.web/'assets/app.js').write_text(secret)
        with self.assertRaises(ValueError) as error:validate({**self.backend,'AMAP_WEB_KEY':secret},self.gateway)
        self.assertNotIn(secret,str(error.exception))
        with self.assertRaises(ValueError):validate(self.backend,{**self.gateway,'AMAP_WEB_KEY':secret})

    def test_build_and_private_file_boundaries_are_checked(self):
        (self.web/'index.html').unlink()
        with self.assertRaises(ValueError):validate(self.backend,self.gateway)
        (self.web/'index.html').write_text('TEST ONLY')
        (self.web/'.env').write_text('TEST ONLY')
        with self.assertRaises(ValueError):validate(self.backend,self.gateway)

    def test_pacing_state_and_bounds_are_private_and_read_only(self):
        for path in (self.web/'rate.sqlite3',Path(self.backend['TRAVEL_DB_PATH']),Path('relative.sqlite3')):
            with self.subTest(path=path),self.assertRaises(ValueError):
                validate({**self.backend,'TRAVEL_AMAP_RATE_DB_PATH':str(path)},self.gateway)
        for name,value in [('MIN_INTERVAL','nan'),('MAX_WAIT','20'),('COOLDOWN','0')]:
            with self.subTest(name=name),self.assertRaises(ValueError):
                validate({**self.backend,'TRAVEL_AMAP_'+name+'_SECONDS':value},self.gateway)
        validate(self.backend,self.gateway)
        self.assertFalse((self.root/'amap-rate.sqlite3').exists())


if __name__=='__main__':unittest.main()
