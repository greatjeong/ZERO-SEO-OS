import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
import test_central_drafts as base
from server import TEST_TITLE


class DraftSaveTests(unittest.TestCase):
    setUpClass = classmethod(base.DraftTests.setUpClass.__func__)
    def setUp(self):
        from cryptography.fernet import Fernet
        self.key = Fernet.generate_key()
        with patch.object(Fernet, 'generate_key', return_value=self.key):
            base.DraftTests.setUp(self)
    login = base.DraftTests.login
    put = base.DraftTests.put
    import_records = base.DraftTests.import_records
    def approval_payload(self):
        return {'url': 'https://example.com', 'confirmDraft': True, 'legacyHistoryReviewed': True}

    def setup_saver(self):
        self.client.put('/api/wordpress/A-1/credentials', headers=self.headers,
            json={'username': 'owner', 'applicationPassword': 'abcdefghijklmnopqrstuvwx'})

    def create(self, payload=None):
        return self.client.post('/api/wordpress/A-1/test-draft', headers=self.headers, json=payload or self.approval_payload())

    def test_confirm_readback_and_no_second_write(self):
        self.setup_saver()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', side_effect=[{'id': 900, 'status': 'draft'}, {'id': 900, 'status': 'draft'}]) as request:
            response = self.create()
            self.assertEqual(response.status_code, 200); self.assertTrue(response.json()['draftConfirmed'])
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0].args[3:5], ('POST', '/posts'))
            self.assertEqual(request.call_args_list[0].args[5]['status'], 'draft')
            self.assertEqual(request.call_args_list[0].args[5]['title'], TEST_TITLE)
            self.assertEqual(request.call_args_list[1].args[3:], ('GET', '/posts/900?context=edit'))
            self.assertEqual(self.create().status_code, 409)
            self.assertEqual(request.call_count, 2)
        self.assertEqual(self.client.get('/api/wordpress/A-1/test-draft').json()['intent']['postId'], 900)

    def test_timeout_and_null_id_preserved_no_retries(self):
        self.setup_saver()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', side_effect=TimeoutError('secret should not leak')) as request:
            response = self.create()
            self.assertEqual(response.status_code, 502); self.assertNotIn('secret', response.text)
            self.assertEqual(self.create().status_code, 409)
            self.assertEqual(self.client.post('/api/wordpress/A-1/test-draft/check', headers=self.headers).status_code, 409)
            self.assertEqual(request.call_count, 1)
        self.assertIsNone(self.client.get('/api/wordpress/A-1/test-draft').json()['intent']['postId'])

    def test_readback_failure_recovers_same_id_only(self):
        self.setup_saver()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', side_effect=[{'id': 900, 'status': 'draft'}, TimeoutError()]):
            self.assertEqual(self.create().status_code, 502)
        with patch('central_draft_save.request_wp', return_value={'id': 900, 'status': 'draft'}) as request:
            response = self.client.post('/api/wordpress/A-1/test-draft/check', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(request.call_args.args[3:], ('GET', '/posts/900?context=edit'))

    def test_history_and_missing_capability_block_creation(self):
        self.setup_saver(); self.import_records()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp') as request:
            self.assertEqual(self.create().status_code, 409); request.assert_not_called()
        with patch('central_draft_save.request_identity', return_value={}), patch('central_draft_save.request_wp') as request:
            self.assertEqual(self.create().status_code, 403); request.assert_not_called()
        self.assertEqual(self.client.post('/api/wordpress/A-1/test-draft', headers=self.headers, json={'confirmDraft': True}).status_code, 400)
        self.assertEqual(self.client.post('/api/wordpress/A-1/test-draft', json=self.approval_payload()).status_code, 403)

    def test_two_simultaneous_requests_send_only_one_post(self):
        self.setup_saver(); started, release = Event(), Event()
        def upstream(*args):
            if args[3] == 'POST':
                started.set(); release.wait(5)
            return {'id': 901, 'status': 'draft'}
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', side_effect=upstream) as request:
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(self.create)
                self.assertTrue(started.wait(5))
                try:
                    self.assertEqual(self.create().status_code, 409)
                finally:
                    release.set()
                self.assertEqual(first.result().status_code, 200)
            self.assertEqual(sum(c.args[3] == 'POST' for c in request.call_args_list), 1)

    def test_restart_preserves_intent_and_blocks_another_slot_same_url(self):
        from dataclasses import replace
        import copy
        from fastapi.testclient import TestClient
        from test_central import DATA, ORIGIN
        import central
        self.setup_saver()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', side_effect=TimeoutError()):
            self.assertEqual(self.create().status_code, 502)
        app = central.create_app(replace(self.settings, wp_key=self.key.decode()))
        with TestClient(app, base_url=ORIGIN) as client:
            headers = self.login(client)
            changed = copy.deepcopy(DATA); changed['sites']['A-2']['url'] = 'https://example.com'
            self.assertEqual(client.put('/api/workspace', json={'baseRevision': 1, 'data': changed}, headers=headers).status_code, 200)
            client.put('/api/wordpress/A-2/credentials', json={'username': 'owner', 'applicationPassword': 'abcdefghijklmnopqrstuvwx'}, headers=headers)
            with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp') as request:
                self.assertEqual(client.post('/api/wordpress/A-2/test-draft', json=self.approval_payload(), headers=headers).status_code, 409)
                request.assert_not_called()
            self.assertIsNone(client.get('/api/wordpress/A-2/test-draft').json()['intent']['postId'])

    def test_non_draft_response_keeps_id_without_success(self):
        self.setup_saver()
        with patch('central_draft_save.request_identity', return_value={'capabilities': {'edit_posts': True}}), patch('central_draft_save.request_wp', return_value={'id': 902, 'status': 'publish'}) as request:
            self.assertEqual(self.create().status_code, 502)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.client.get('/api/wordpress/A-1/test-draft').json()['intent']['postId'], 902)
