import unittest
from unittest.mock import patch
from dataclasses import replace
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import central
import test_central as base
from test_central import ORIGIN


class DraftTests(unittest.TestCase):
    setUpClass = classmethod(base.CentralTests.setUpClass.__func__)
    login = base.CentralTests.login
    put = base.CentralTests.put

    def setUp(self):
        base.CentralTests.setUp(self)
        self.app = central.create_app(replace(self.settings, wp_key=Fernet.generate_key().decode()))
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(self.client.close)
        self.headers = self.login(); self.put(self.headers)
        self.payload = {'format': 'zero-seo-os-draft-history', 'version': 1, 'records': [
            {'url': 'https://example.com', 'postId': i, 'createdAt': 'legacy', 'source': 'desktop' if i == 737 else 'laptop'}
            for i in (737, 738, None)]}

    def import_records(self):
        return self.client.post('/api/draft-history/import', json=self.payload, headers=self.headers)

    def test_preview_no_writes_append_only_and_idempotent(self):
        self.assertEqual(self.client.post('/api/draft-history/preview', json=self.payload, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/draft-history').json()['records'], [])
        self.assertEqual(self.import_records().json()['added'], 3)
        self.assertEqual(self.import_records().json()['existing'], 3)
        self.assertEqual(len(self.client.get('/api/draft-history').json()['records']), 3)
        self.assertNotIn('draft_history', self.client.get('/api/workspace').text)

    def test_invalid_row_rolls_back_entire_import(self):
        self.payload['records'][1]['password'] = 'never-import'
        self.assertEqual(self.import_records().status_code, 400)
        self.assertEqual(self.client.get('/api/draft-history').json()['records'], [])
        self.assertEqual(self.client.post('/api/draft-history/import', json=self.payload).status_code, 403)

    def test_check_only_reads_existing_id_and_rejects_uncertain(self):
        self.import_records()
        self.client.put('/api/wordpress/A-1/credentials', headers=self.headers,
            json={'username': 'owner', 'applicationPassword': 'abcdefghijklmnopqrstuvwx'})
        rows = self.client.get('/api/draft-history').json()['records']
        with patch('central_drafts.request_wp', return_value={'id': 738, 'status': 'draft'}) as request:
            row = next(row for row in rows if row['postId'] == 738)
            response = self.client.post(f"/api/wordpress/A-1/draft-history/{row['fingerprint']}/check", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(request.call_args.args[3:], ('GET', '/posts/738?context=edit'))
            uncertain = next(row for row in rows if row['postId'] is None)
            self.assertEqual(self.client.post(f"/api/wordpress/A-1/draft-history/{uncertain['fingerprint']}/check", headers=self.headers).status_code, 409)
            self.assertEqual(request.call_count, 1)
        with patch('central_drafts.request_wp', return_value={'id': 738, 'status': 'publish'}):
            self.assertEqual(self.client.post(f"/api/wordpress/A-1/draft-history/{row['fingerprint']}/check", headers=self.headers).status_code, 502)
        self.assertEqual(len(self.client.get('/api/draft-history').json()['records']), 3)
