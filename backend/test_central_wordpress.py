import copy
import unittest
from dataclasses import replace
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import test_central as base
from test_central import DATA, ORIGIN
import central
from server import VerificationError


class WordPressTests(unittest.TestCase):
    setUpClass = classmethod(base.CentralTests.setUpClass.__func__)
    login = base.CentralTests.login
    put = base.CentralTests.put
    def setUp(self):
        base.CentralTests.setUp(self)
        self.key = Fernet.generate_key().decode()
        self.app = central.create_app(replace(self.settings, wp_key=self.key))
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def register(self, headers):
        return self.client.put('/api/wordpress/A-1/credentials', headers=headers,
            json={'username': 'test-owner', 'applicationPassword': 'abcd efgh ijkl mnop qrst uvwx'})

    def test_credentials_encrypted_backup_excluded_restart(self):
        headers = self.login(); self.put(headers)
        self.assertEqual(self.register(headers).json(), {'configured': True, 'verified': False})
        raw = self.app.state.store.path.read_bytes()
        self.assertNotIn(b'abcdefghijklmnopqrstuvwx', raw)
        self.assertNotIn(b'test-owner', raw)
        self.assertNotIn('applicationPassword', self.client.get('/api/workspace').text)
        restarted = central.create_app(replace(self.settings, wp_key=self.key))
        with TestClient(restarted, base_url=ORIGIN) as client:
            h = self.login(client)
            with patch('central_wordpress.request_identity', return_value={'id': 1, 'capabilities': {'edit_posts': True}}) as request:
                response = client.post('/api/wordpress/A-1/verify', headers=h)
            self.assertTrue(response.json()['verified']); request.assert_called_once()

    def test_verification_failure_and_address_change(self):
        headers = self.login(); self.put(headers); self.register(headers)
        with patch('central_wordpress.request_identity', side_effect=VerificationError('HTTP 401')):
            self.assertEqual(self.client.post('/api/wordpress/A-1/verify', headers=headers).status_code, 502)
        changed = copy.deepcopy(DATA); changed['sites']['A-1']['url'] = 'https://new.example'
        self.put(headers, 1, changed)
        with patch('central_wordpress.request_identity') as request:
            self.assertEqual(self.client.post('/api/wordpress/A-1/verify', headers=headers).status_code, 409)
            request.assert_not_called()

    def test_wrong_key_preserves_ciphertext(self):
        headers = self.login(); self.put(headers); self.register(headers)
        app = central.create_app(replace(self.settings, wp_key=Fernet.generate_key().decode()))
        with TestClient(app, base_url=ORIGIN) as client:
            h = self.login(client)
            self.assertEqual(client.post('/api/wordpress/A-1/verify', headers=h).status_code, 503)
        with patch('central_wordpress.request_identity', return_value={'id': 1}):
            response = self.client.post('/api/wordpress/A-1/verify', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['permissions']['editPosts'])

    def test_secret_endpoints_require_csrf_and_valid_input(self):
        self.assertEqual(self.register({}).status_code, 401)
        headers = self.login(); self.put(headers)
        self.assertEqual(self.register({'Origin': ORIGIN}).status_code, 403)
        self.assertEqual(self.client.put('/api/wordpress/A-1/credentials', headers=headers,
            json={'username': 'owner', 'applicationPassword': 'wrong'}).status_code, 400)
        self.assertEqual(self.client.post('/api/wordpress/A-2/verify', headers=headers).status_code, 400)

    def test_changed_credentials_during_verification_never_return_success(self):
        headers = self.login(); self.put(headers); self.register(headers)
        def changed(*_args):
            self.register(headers)
            return {'id': 1, 'capabilities': {'edit_posts': True}}
        with patch('central_wordpress.request_identity', side_effect=changed):
            self.assertEqual(self.client.post('/api/wordpress/A-1/verify', headers=headers).status_code, 409)
