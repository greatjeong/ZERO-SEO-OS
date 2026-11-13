import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import central
from central_auth import hash_password, verify_password

ORIGIN = 'https://zero.example'
PASSWORD = 'test-only-password-long-enough'
DATA = {'format': 'zero-seo-os-backup', 'version': 2, 'exportedAt': '2026-11-13',
        'sites': {'A-1': {'name': '사이트', 'url': 'https://example.com'}, 'A-2': {'name': '', 'url': ''}},
        'keywordsBySite': {'A-1': ['보존 키워드'], 'A-2': ['분리 키워드']},
        'jobs': [{'id': 'old-job', 'site': 'A-1', 'keyword': '보존 키워드', 'status': '취소', 'createdAt': '2026-11-13'}]}


class CentralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = hash_password(PASSWORD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = central.Settings(ORIGIN, Path(self.tmp.name) / 'central', self.encoded)
        self.app = central.create_app(self.settings)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def login(self, client=None):
        client = client or self.client
        response = client.post('/api/login', json={'password': PASSWORD}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        return {'Origin': ORIGIN, 'X-CSRF-Token': response.json()['csrf']}

    def put(self, headers, revision=0, data=None):
        return self.client.put('/api/workspace', json={'baseRevision': revision, 'data': data or DATA}, headers=headers)

    def test_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            central.create_app()
        with self.assertRaises(ValueError):
            central.Settings('http://zero.example', Path(self.tmp.name), self.encoded)
        with self.assertRaises(ValueError):
            central.Settings(ORIGIN, Path(self.tmp.name), '')
        self.assertNotIn(self.encoded, repr(self.settings))

    def test_all_data_routes_require_login(self):
        for path in ['/api/session', '/api/workspace', '/api/snapshots', '/api/snapshots/1']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.put({}, data=DATA).status_code, 401)
        self.assertEqual(self.client.get('/api/health').json()['mode'], 'private-owner')

    def test_origin_password_and_cookie_security(self):
        self.assertEqual(self.client.post('/api/login', json={'password': PASSWORD}).status_code, 403)
        self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}, headers={'Origin': ORIGIN}).status_code, 401)
        self.login()
        response = self.client.post('/api/login', json={'password': PASSWORD}, headers={'Origin': ORIGIN})
        cookie = response.headers['set-cookie']
        for value in ['HttpOnly', 'Secure', 'SameSite=strict', 'Path=/']:
            self.assertIn(value, cookie)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_csrf_and_cross_origin_write_rejected(self):
        headers = self.login()
        for h in [{}, {'Origin': ORIGIN}, {**headers, 'Origin': 'https://evil.example'}]:
            self.assertEqual(self.put(h).status_code, 403)
        self.assertIsNone(self.client.get('/api/workspace').json()['data'])

    def test_logout_revokes_session(self):
        headers = self.login()
        self.assertEqual(self.client.post('/api/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/workspace').status_code, 401)

    def test_expired_session_rejected(self):
        self.login()
        with sqlite3.connect(self.app.state.store.path) as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get('/api/workspace').status_code, 401)

    def test_second_browser_and_app_restart_share_saved_data(self):
        headers = self.login()
        self.assertEqual(self.put(headers).status_code, 200)
        second = TestClient(central.create_app(self.settings), base_url=ORIGIN)
        self.addCleanup(second.close)
        self.login(second)
        self.assertEqual(second.get('/api/workspace').json()['data'], DATA)
        self.assertEqual(second.get('/api/workspace').json()['revision'], 1)

    def test_conflict_preserves_current_data_and_history(self):
        headers = self.login()
        self.assertEqual(self.put(headers).status_code, 200)
        changed = {**DATA, 'jobs': []}
        self.assertEqual(self.put(headers, data=changed).status_code, 409)
        self.assertEqual(self.client.get('/api/workspace').json()['data'], DATA)
        self.assertEqual(self.put(headers, 1, changed).status_code, 200)
        self.assertEqual(self.client.get('/api/snapshots/1').json()['data'], DATA)
        self.assertEqual(len(self.client.get('/api/snapshots').json()['snapshots']), 2)

    def test_invalid_backup_does_not_write(self):
        headers = self.login()
        for mutate in [lambda d: d.update(password='not-allowed'),
                       lambda d: d['sites']['A-1'].update(token='not-allowed'),
                       lambda d: d['jobs'].append(d['jobs'][0].copy()),
                       lambda d: d['sites']['A-1'].update(url='https://u:p@example.com')]:
            data = copy.deepcopy(DATA); mutate(data)
            self.assertEqual(self.put(headers, data=data).status_code, 400)
        self.assertEqual(self.client.get('/api/workspace').json()['revision'], 0)

    def test_v1_import_preview_preserves_sites_and_never_writes(self):
        headers = self.login(); self.put(headers)
        v1 = {k: v for k, v in DATA.items() if k != 'sites'}
        v1.update(version=1, jobs=[])
        result = self.client.post('/api/import/preview', json=v1, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['sites'], DATA['sites'])
        self.assertEqual(result.json()['baseRevision'], 1)
        self.assertEqual(self.client.get('/api/workspace').json()['data'], DATA)

    def test_body_bounds_and_json_format(self):
        headers = self.login()
        self.assertEqual(self.client.put('/api/workspace', content='invalid', headers={**headers, 'Content-Type': 'application/json'}).status_code, 400)
        self.assertEqual(self.client.put('/api/workspace', content='x', headers=headers).status_code, 415)
        self.assertEqual(self.client.put('/api/workspace', content='x' * (central.MAX_BODY + 1), headers={**headers, 'Content-Type': 'application/json'}).status_code, 413)

    def test_login_throttle(self):
        for _ in range(5):
            with patch.object(central, 'verify_password', return_value=False):
                self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}, headers={'Origin': ORIGIN}).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': PASSWORD}, headers={'Origin': ORIGIN}).status_code, 429)

    def test_hash_and_sessions_are_not_plaintext(self):
        self.login()
        self.assertNotIn(PASSWORD, self.encoded)
        with sqlite3.connect(self.app.state.store.path) as db:
            row = db.execute('SELECT token_hash FROM sessions').fetchone()
        self.assertNotEqual(row[0], self.client.cookies.get(central.COOKIE))
        self.assertNotIn(PASSWORD.encode(), self.app.state.store.path.read_bytes())
        self.assertFalse(verify_password('incorrect', self.encoded))

    def test_password_rotation_invalidates_existing_sessions(self):
        self.login()
        with patch.object(central, 'hashlib') as hashes:
            # Use a different valid hash string; no actual owner credential changes.
            hashes.sha256.return_value.hexdigest.return_value = 'different-auth-revision'
            rotated = central.create_app(self.settings)
        client = TestClient(rotated, base_url=ORIGIN)
        self.addCleanup(client.close)
        client.cookies.update(self.client.cookies)
        self.assertEqual(client.get('/api/session').status_code, 401)

    def test_future_schema_not_overwritten(self):
        with sqlite3.connect(self.app.state.store.path) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            central.create_app(self.settings)
        with sqlite3.connect(self.app.state.store.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_no_legacy_data_files_created(self):
        self.login()
        names = {p.name for p in self.settings.data_dir.iterdir()}
        self.assertEqual(names, {'central.sqlite3'})
        self.assertEqual(self.client.get('/api/sites/test-draft').status_code, 404)

    def test_concurrent_writes_have_exactly_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        def write(_):
            try:
                return self.app.state.store.save(0, DATA)['revision']
            except central.HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [1, 2]))
        self.assertEqual(sorted(results), [1, 409])
        self.assertEqual(self.app.state.store.current()['revision'], 1)

    def test_built_ui_served_without_exposing_repository_or_data(self):
        static = Path(self.tmp.name) / 'dist'
        (static / 'assets').mkdir(parents=True)
        (static / 'central.html').write_text('<html>test central login</html>')
        (static / 'assets' / 'main.js').write_text('/* public bundle */')
        cfg = central.Settings(ORIGIN, self.settings.data_dir, self.encoded, static)
        client = TestClient(central.create_app(cfg), base_url=ORIGIN)
        self.addCleanup(client.close)
        self.assertEqual(client.get('/').url.path, '/central.html')
        self.assertIn('test central login', client.get('/central.html').text)
        self.assertEqual(client.get('/assets/main.js').status_code, 200)
        for path in ['/central.sqlite3', '/.env', '/server.py', '/openapi.json', '/api/sites/test-draft']:
            self.assertEqual(client.get(path).status_code, 404)

    def test_password_hash_work_is_concurrency_bounded(self):
        gate = self.app.state.login_gate
        gate.acquire(); gate.acquire()
        try:
            with patch.object(central, 'verify_password') as verify:
                response = self.client.post('/api/login', json={'password': PASSWORD}, headers={'Origin': ORIGIN})
            self.assertEqual(response.status_code, 429)
            verify.assert_not_called()
        finally:
            gate.release(); gate.release()
