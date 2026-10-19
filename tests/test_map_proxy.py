"""Map SDK gateway checks: explicit TEST ONLY transport, no authorized traffic."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from travel.map_proxy import PREFIX, MAX_BYTES, MapProxy, map_service
from starlette.requests import Request

KEY = 'TEST_ONLY_JS_KEY'
CODE = 'TEST_ONLY_SERVER_SECURITY_CODE'
PATH = PREFIX + '/v4/map/styles'


class MapProxyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {'TRAVEL_DB_PATH': str(Path(self.folder.name) / 'test.sqlite3'),
            'TRAVEL_AUTH_MODE': 'local', 'AMAP_JS_KEY': KEY, 'AMAP_JS_SECURITY_CODE': CODE,
            'TRAVEL_CORS_ORIGINS': 'http://testserver', 'TRAVEL_TOOL_CONCURRENCY': '1',
            'TRAVEL_LIMIT_TOOLS': '60', 'TRAVEL_LIMIT_TOOLS_GLOBAL': '180'})
        self.env.start()
        self.addCleanup(self.env.stop)
        from main import app
        self.app = app
        self.client = TestClient(app).__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.calls = []

    def upstream(self, handler=None):
        def record(request):
            self.calls.append(request)
            return handler(request) if handler else httpx.Response(200, content=b'TEST ONLY map data', headers={'content-type': 'application/octet-stream'})
        self.app.state.map_proxy.client._transport = httpx.MockTransport(record)

    def get(self, path=PATH, **kwargs):
        kwargs.setdefault('params', {'key': KEY})
        return self.client.get(path, **kwargs)

    def test_missing_credentials_fail_without_upstream(self):
        self.upstream()
        for field in ('key', 'code'):
            with patch.object(self.app.state.map_proxy, field, ''):
                response = self.get()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['error']['code'], 'map_proxy_not_configured')
        self.assertEqual(self.calls, [])

    def test_fixed_upstreams_inject_server_code_and_do_not_forward_private_headers(self):
        self.upstream(lambda _: httpx.Response(200, content=b'TEST ONLY', headers={
            'content-type': 'application/javascript; charset=utf-8', 'set-cookie': 'TEST_ONLY=secret',
            'location': 'https://test.invalid', 'access-control-allow-origin': '*'}))
        for suffix, host in (('/v4/map/styles', 'webapi.amap.com'), ('/v3/log/init', 'restapi.amap.com')):
            response = self.get(PREFIX + suffix, params={'key': KEY, 'callback': 'AMap.callbacks.jsonp_1'},
                headers={'Authorization': 'Bearer TEST_ONLY_PRIVATE', 'Cookie': 'private=TEST_ONLY',
                         'Referer': 'http://testserver/private?token=TEST_ONLY', 'Origin': 'http://testserver'})
            self.assertEqual(response.status_code, 200)
            request = self.calls[-1]
            self.assertEqual(request.url.host, host)
            self.assertEqual(request.url.path, suffix)
            self.assertEqual(request.url.params['jscode'], CODE)
            self.assertEqual(request.url.params['key'], KEY)
            self.assertEqual(request.headers['referer'], 'http://testserver/')
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('origin', request.headers)
            self.assertNotIn('set-cookie', response.headers)
            self.assertNotIn('location', response.headers)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_business_paths_traversal_and_methods_cannot_be_forwarded(self):
        self.upstream()
        for suffix in ('v3/place/text', 'v3/direction/walking', 'v4/map/styles/extra',
                       'https://test.invalid/', '%2F%2Ftest.invalid', 'v4/map/styles%2F..%2F..%2Fplace'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.get(PREFIX + '/' + suffix).status_code, 404)
        self.assertEqual(self.client.post(PATH).status_code, 405)
        self.assertEqual(self.calls, [])

    def test_keys_duplicate_parameters_injection_and_query_size_are_rejected(self):
        self.upstream()
        cases = [({'key': 'TEST_ONLY_OTHER'}, 403), ({}, 403),
            ([('key', KEY), ('key', KEY)], 422), ([('key', KEY), ('KEY', KEY)], 422),
            ({'key': KEY, 'jscode': 'TEST_ONLY_CLIENT_CODE'}, 422),
            ({'key': KEY, 'JsCode': CODE}, 422),
            ({'key': KEY, 'callback': 'alert(1)//'}, 422),
            ({'key': KEY, 'Callback': 'AMap.cb'}, 422),
            ({'key': KEY, 'callback': 'x' * 129}, 422),
            ({'key': KEY, 'data': 'x' * 4096}, 422),
            ({'key': KEY, **{f'p{i}': 'x' for i in range(32)}}, 422)]
        for params, status in cases:
            with self.subTest(params=params):
                self.assertEqual(self.get(params=params).status_code, status)
        self.assertEqual(self.calls, [])

    def test_cross_site_and_untrusted_referrers_are_rejected_even_locally(self):
        self.upstream()
        for headers in ({'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'https://test.invalid'},
                        {'Referer': 'https://test.invalid/'}, {'Referer': 'http://[malformed'}):
            self.assertEqual(self.get(headers=headers).status_code, 403)
        self.assertEqual(self.calls, [])

    def test_upstream_errors_redirects_html_oversize_and_secret_echo_fail_closed(self):
        for response in (httpx.Response(302, headers={'location': 'http://127.0.0.1/private'}),
                         httpx.Response(429), httpx.Response(500),
                         httpx.Response(200, text='<script>TEST ONLY</script>', headers={'content-type': 'text/html'}),
                         httpx.Response(200, content=b'x' * (MAX_BYTES + 1), headers={'content-type': 'application/octet-stream'}),
                         httpx.Response(200, content=CODE.encode(), headers={'content-type': 'application/javascript'})):
            self.upstream(lambda _, value=response: value)
            result = self.get()
            self.assertEqual(result.status_code, 502)
            self.assertNotIn(CODE, result.text)
            self.assertTrue(response.is_closed)
        self.assertEqual(len(self.calls), 6)  # No redirect or retry request.

    def test_transport_failures_are_sanitized_and_release_concurrency(self):
        for error, status in ((httpx.ReadTimeout(CODE), 504), (httpx.ConnectError(CODE), 502)):
            def failed(_, error=error): raise error
            self.upstream(failed)
            result = self.get()
            self.assertEqual(result.status_code, status)
            self.assertNotIn(CODE, result.text)
        self.upstream()
        self.assertEqual(self.get().status_code, 200)

    def test_verbose_httpx_logs_do_not_expose_server_code(self):
        self.upstream()
        with self.assertLogs('httpx', level=logging.INFO) as captured:
            self.assertEqual(self.get().status_code, 200)
        self.assertNotIn(CODE, '\n'.join(captured.output))
        self.assertIn('[REDACTED]', '\n'.join(captured.output))

    def test_persisted_tool_quota_limits_proxy_without_blocking_status(self):
        self.upstream()
        self.app.state.travel.limits.tool_limit = 1
        self.assertEqual(self.get().status_code, 200)
        result = self.get()
        self.assertEqual(result.status_code, 429)
        self.assertIn('retry-after', result.headers)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.client.get('/api/v1/travel/auth/status').status_code, 200)

    def test_concurrent_proxy_requests_reject_without_waiting_then_release(self):
        started, finish = Event(), Event()
        async def slow(request):
            started.set()
            while not finish.is_set(): await asyncio.sleep(.01)
            return httpx.Response(200, content=b'TEST ONLY', headers={'content-type': 'application/octet-stream'})
        self.app.state.map_proxy.client._transport = httpx.MockTransport(slow)
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(self.get)
            try:
                self.assertTrue(started.wait(5))
                result = self.get()
                self.assertEqual(result.status_code, 429)
                self.assertEqual(result.json()['error']['code'], 'tool_busy')
            finally:
                finish.set()
            self.assertEqual(request.result(timeout=5).status_code, 200)
        self.upstream()
        self.assertEqual(self.get().status_code, 200)

    def test_cookie_and_bearer_identity_cover_sdk_path_and_logout_revokes_access(self):
        self.upstream()
        auth = self.app.state.auth
        auth.mode = 'session'
        auth.create_user('test-map', 'TEST ONLY map proxy password')
        self.assertEqual(self.get().status_code, 401)
        login = self.client.post('/api/v1/travel/auth/login', headers={'X-Travel-Client': 'web'},
            json={'username': 'test-map', 'password': 'TEST ONLY map proxy password', 'transport': 'cookie'})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.get().status_code, 200)
        token = login.json()['csrf_token']
        self.assertEqual(self.client.post('/api/v1/travel/auth/logout', headers={'X-CSRF-Token': token}).status_code, 200)
        self.assertEqual(self.get().status_code, 401)
        login = self.client.post('/api/v1/travel/auth/login', json={
            'username': 'test-map', 'password': 'TEST ONLY map proxy password', 'transport': 'bearer'})
        self.assertEqual(self.get(headers={'Authorization': 'Bearer ' + login.json()['access_token']}).status_code, 200)

    def test_canceled_request_releases_slot_and_client_closes_at_shutdown(self):
        async def exercise():
            started = asyncio.Event()
            async def stalled(request):
                started.set()
                await asyncio.sleep(60)
            proxy = MapProxy()
            proxy.client._transport = httpx.MockTransport(stalled)
            state = self.app.state
            old = state.map_proxy
            state.map_proxy = proxy
            scope = {'type': 'http', 'method': 'GET', 'path': PATH, 'query_string': ('key=' + KEY).encode(),
                     'headers': [], 'app': self.app, 'state': {'identity': self.app.state.auth.identify(Request({'type': 'http', 'headers': []}))}}
            try:
                task = asyncio.create_task(map_service('v4/map/styles', Request(scope)))
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                with state.travel.limits.tool('local'): pass
            finally:
                state.map_proxy = old
                await proxy.close()
            self.assertTrue(proxy.client.is_closed)
        asyncio.run(exercise())


if __name__ == '__main__': unittest.main()
