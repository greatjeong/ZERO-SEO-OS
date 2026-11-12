import http.client
import json
import os
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

import server


ENV = {'ZERO_WP_A1_URL': 'https://example.com/blog', 'ZERO_WP_A1_USER': 'editor',
       'ZERO_WP_A1_APP_PASSWORD': 'secret-never-return'}
PAYLOAD = {'site': 'A-1', 'url': 'https://example.com/blog'}


class ConnectorTests(unittest.TestCase):
    def test_requires_config(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(server.VerificationError):
            server.verify(PAYLOAD)

    def test_url_allowlist_before_network(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(server, 'request_identity') as request:
            with self.assertRaises(server.VerificationError):
                server.verify({**PAYLOAD, 'url': 'https://attacker.example'})
            request.assert_not_called()

    def test_success_requires_upstream(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(server, 'request_identity') as request:
            result = server.verify(PAYLOAD)
            request.assert_called_once_with(ENV['ZERO_WP_A1_URL'], 'editor', 'secret-never-return')
            self.assertTrue(result['verified'])
            self.assertNotIn('secret', json.dumps(result))

    def test_failure_propagates(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(server, 'request_identity', side_effect=server.VerificationError('401')):
            with self.assertRaises(server.VerificationError):
                server.verify(PAYLOAD)

    def test_permission_results_and_no_private_data(self):
        for caps, expected in [
            ({'edit_posts': True, 'publish_posts': True}, {'editPosts': True, 'publishPosts': True}),
            ({'edit_posts': True, 'publish_posts': False}, {'editPosts': True, 'publishPosts': False}),
            ({}, {'editPosts': False, 'publishPosts': False}),
            (None, {'editPosts': None, 'publishPosts': None}),
            ({'edit_posts': 'true', 'publish_posts': 1}, {'editPosts': None, 'publishPosts': None}),
        ]:
            identity = {'capabilities': caps, 'email': 'private@example.com', 'other': 'secret'}
            with self.subTest(caps=caps), patch.dict(os.environ, ENV, clear=True), patch.object(server, 'request_identity', return_value=identity):
                result = server.verify(PAYLOAD, include_permissions=True)
                self.assertTrue(result['verified'])
                self.assertEqual(result['permissions'], expected)
                self.assertNotIn('private@example.com', json.dumps(result))
                self.assertNotIn('secret', json.dumps(result))

    def test_permission_failure_never_succeeds(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(server, 'request_identity', side_effect=server.VerificationError('denied')):
            with self.assertRaises(server.VerificationError):
                server.verify(PAYLOAD, include_permissions=True)

    def test_reject_unsafe_urls(self):
        for url in ['http://example.com', 'https://u:p@example.com', 'https://example.com/?token=x',
                    'https://example.com/#x', 'https://example.com:8888', 'https://example.com\\@evil.com']:
            with self.subTest(url=url), self.assertRaises(server.VerificationError):
                server.normalize_url(url)

    def test_private_and_mixed_dns_blocked(self):
        for addresses in [['127.0.0.1'], ['::1'], ['169.254.169.254'], ['8.8.8.8', '10.0.0.1']]:
            entries = [(2, 1, 6, '', (ip, 443)) for ip in addresses]
            with patch.object(server.socket, 'getaddrinfo', return_value=entries), self.assertRaises(server.VerificationError):
                server.public_addresses('example.com')

    def test_upstream_responses(self):
        cases = [(200, 'application/json', {'id': 1, 'username': 'editor'}, True),
                 (200, 'application/json', {'id': 0, 'username': 'editor'}, False),
                 (200, 'application/json', {'id': 1, 'username': 'someone'}, False),
                 (200, 'text/html', {}, False), (301, 'application/json', {}, False),
                 (401, 'application/json', {}, False), (403, 'application/json', {}, False)]
        for status, content_type, body, success in cases:
            response = MagicMock(status=status)
            response.getheader.return_value = content_type
            response.read.return_value = json.dumps(body).encode()
            conn = MagicMock()
            conn.getresponse.return_value = response
            with self.subTest(status=status, body=body), patch.object(server, 'public_addresses', return_value=['8.8.8.8']), patch.object(server, 'PinnedHTTPSConnection', return_value=conn):
                if success:
                    server.request_identity('https://example.com/blog', 'editor', 'secret')
                    self.assertEqual(conn.request.call_args.args[0], 'GET')
                    self.assertEqual(conn.request.call_args.args[1], '/blog/wp-json/wp/v2/users/me?context=edit')
                else:
                    with self.assertRaises(server.VerificationError):
                        server.request_identity('https://example.com/blog', 'editor', 'secret')
                conn.close.assert_called_once()


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def send(self, origin, host=server.HOST, path='/api/sites/verify'):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=2)
        conn.request('POST', path, json.dumps(PAYLOAD),
                     {'Content-Type': 'application/json', 'Origin': origin, 'Host': host})
        response = conn.getresponse()
        result = response.status, response.getheader('Access-Control-Allow-Origin'), response.read()
        conn.close()
        return result

    def test_origin_and_host_rejected(self):
        with patch.object(server, 'verify') as verify:
            self.assertEqual(self.send('https://attacker.example')[0], 403)
            self.assertEqual(self.send(server.ORIGIN, 'attacker.example')[0], 403)
            verify.assert_not_called()

    def test_generic_error_does_not_leak_secrets(self):
        with patch.object(server, 'verify', side_effect=RuntimeError('SECRET')):
            status, origin, body = self.send(server.ORIGIN)
            self.assertEqual(status, 502)
            self.assertEqual(origin, server.ORIGIN)
            self.assertNotIn(b'SECRET', body)
            self.assertFalse(json.loads(body)['verified'])

    def test_permissions_route(self):
        with patch.object(server, 'verify', return_value={'verified': True, 'permissions': {'editPosts': True, 'publishPosts': False}}) as verify:
            status, _, body = self.send(server.ORIGIN, path='/api/sites/permissions')
            self.assertEqual(status, 200)
            verify.assert_called_once_with(PAYLOAD, include_permissions=True)
            self.assertFalse(json.loads(body)['permissions']['publishPosts'])

    def test_permissions_origin_rejected(self):
        with patch.object(server, 'verify') as verify:
            self.assertEqual(self.send('https://attacker.example', path='/api/sites/permissions')[0], 403)
            verify.assert_not_called()

    def test_draft_origin_rejected(self):
        with patch.object(server, 'test_draft') as draft:
            self.assertEqual(self.send('https://attacker.example', path='/api/sites/test-draft')[0], 403)
            draft.assert_not_called()

    def test_draft_route(self):
        with patch.object(server, 'test_draft', return_value={'draftConfirmed': True, 'postId': 42}) as draft:
            status, _, body = self.send(server.ORIGIN, path='/api/sites/test-draft')
            self.assertEqual(status, 200)
            draft.assert_called_once_with(PAYLOAD)
            self.assertTrue(json.loads(body)['draftConfirmed'])


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in [patch.object(server, 'STATE_DB', Path(self.temp.name) / '.state/test.sqlite3'),
                        patch.dict(os.environ, ENV, clear=True),
                        patch.object(server, 'request_identity', return_value={'capabilities': {'edit_posts': True}})]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_draft_create_read_and_reuse(self):
        with patch.object(server, 'request_wp', return_value={'id': 42, 'status': 'draft'}) as request:
            result = server.test_draft(PAYLOAD)
            self.assertTrue(result['draftConfirmed'])
            self.assertFalse(result['reused'])
            self.assertEqual(request.call_args_list[0].args[3:5], ('POST', '/posts'))
            body = request.call_args_list[0].args[5]
            self.assertEqual(body['status'], 'draft')
            self.assertEqual(body['title'], server.TEST_TITLE)
            self.assertEqual(body['content'], server.TEST_CONTENT)
            self.assertEqual(request.call_args_list[1].args[3:], ('GET', '/posts/42?context=edit'))
            reused = server.test_draft(PAYLOAD)
            self.assertTrue(reused['reused'])
            self.assertEqual(reused['postId'], 42)
            self.assertEqual(len([c for c in request.call_args_list if c.args[3] == 'POST']), 1)

    def test_write_requires_confirmed_capability(self):
        for caps in [None, {}, {'edit_posts': False}, {'edit_posts': 1}]:
            with self.subTest(caps=caps), patch.object(server, 'request_identity', return_value={'capabilities': caps}), patch.object(server, 'request_wp') as request:
                with self.assertRaises(server.VerificationError):
                    server.test_draft(PAYLOAD)
                request.assert_not_called()

    def test_timeout_blocks_second_write_across_calls(self):
        with patch.object(server, 'request_wp', side_effect=TimeoutError('secret')) as request:
            with self.assertRaises(server.VerificationError) as error:
                server.test_draft(PAYLOAD)
            self.assertNotIn('secret', str(error.exception))
            with self.assertRaises(server.VerificationError):
                server.test_draft(PAYLOAD)
            self.assertEqual(request.call_count, 1)

    def test_read_timeout_recovers_without_another_write(self):
        with patch.object(server, 'request_wp', side_effect=[{'id': 42, 'status': 'draft'}, TimeoutError(), {'id': 42, 'status': 'draft'}]) as request:
            with self.assertRaises(server.VerificationError):
                server.test_draft(PAYLOAD)
            result = server.test_draft(PAYLOAD)
            self.assertTrue(result['draftConfirmed'])
            self.assertTrue(result['reused'])
            self.assertEqual(len([c for c in request.call_args_list if c.args[3] == 'POST']), 1)

    def test_non_draft_response_never_success(self):
        with patch.object(server, 'request_wp', return_value={'id': 42, 'status': 'publish'}) as request:
            with self.assertRaisesRegex(server.VerificationError, '초안이 아닙니다'):
                server.test_draft(PAYLOAD)
            with self.assertRaises(server.VerificationError):
                server.test_draft(PAYLOAD)
            self.assertEqual(request.call_count, 1)

    def test_readback_must_confirm_draft_and_id(self):
        for data in [{'id': 42, 'status': 'pending'}, {'id': 43, 'status': 'draft'}]:
            with self.subTest(data=data), self.assertRaises(server.VerificationError):
                server.validate_draft(data, 42)
        with patch.object(server, 'request_wp', side_effect=[{'id': 42, 'status': 'draft'}, {'id': 42, 'status': 'publish'}]):
            with self.assertRaises(server.VerificationError):
                server.test_draft(PAYLOAD)

    def test_existing_status_is_rechecked(self):
        with patch.object(server, 'request_wp', return_value={'id': 42, 'status': 'draft'}):
            server.test_draft(PAYLOAD)
        with patch.object(server, 'request_wp', return_value={'id': 42, 'status': 'publish'}) as request:
            with self.assertRaises(server.VerificationError):
                server.test_draft(PAYLOAD)
            self.assertEqual(request.call_args.args[3], 'GET')

    def test_browser_cannot_request_publish(self):
        with patch.object(server, 'request_wp') as request:
            with self.assertRaises(server.VerificationError):
                server.test_draft({**PAYLOAD, 'status': 'publish'})
            request.assert_not_called()

    def test_same_site_in_different_slot_does_not_duplicate(self):
        with patch.object(server, 'request_wp', return_value={'id': 42, 'status': 'draft'}) as request:
            server.test_draft(PAYLOAD)
            extra = {key.replace('_A1_', '_A2_'): value for key, value in ENV.items()}
            with patch.dict(os.environ, extra):
                result = server.test_draft({**PAYLOAD, 'site': 'A-2'})
            self.assertTrue(result['reused'])
            self.assertEqual(len([c for c in request.call_args_list if c.args[3] == 'POST']), 1)

    def test_concurrent_click_only_one_write(self):
        started = threading.Event()
        release = threading.Event()
        errors = []
        def upstream(_url, _user, _password, method, _endpoint, body=None):
            if method == 'POST':
                started.set()
                release.wait(3)
            return {'id': 42, 'status': 'draft'}
        def first():
            try:
                server.test_draft(PAYLOAD)
            except Exception as error:
                errors.append(error)
        with patch.object(server, 'request_wp', side_effect=upstream) as request:
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(started.wait(3))
                with self.assertRaises(server.VerificationError):
                    server.test_draft(PAYLOAD)
            finally:
                release.set()
                worker.join(4)
            self.assertFalse(errors)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len([c for c in request.call_args_list if c.args[3] == 'POST']), 1)


if __name__ == '__main__':
    unittest.main()
