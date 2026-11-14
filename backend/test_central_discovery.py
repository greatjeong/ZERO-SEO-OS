import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from central import Settings, create_app
from central_auth import hash_password
from central_store import Store
from central_discovery import Discovery, parse_response, platform_for, PageSignals, public_url

KEYWORD = '카카오택시 분실물 조회'
def fixture(engine):
    return {'search_metadata': {'status': 'Success'}, 'search_parameters': {'engine': engine, 'q' if engine == 'google' else 'query': KEYWORD},
            'organic_results' if engine == 'google' else 'web_results': [
                {'position': 1, 'title': '제외할 네이버', 'link': 'https://blog.naver.com/a/1'},
                {'position': 2, 'title': '택시 분실물', 'link': 'https://ek5524.tistory.com/147'},
                {'position': 3, 'title': '독립 도메인', 'link': 'https://namtaegi.com/how-to-find-lost-items-taxi/'}],
            'ads': [{'link': 'https://advertisement.tistory.com/1'}]}

class FakeProvider:
    def __init__(self, fail=None): self.calls = []; self.fail = fail
    def search(self, engine, keyword):
        self.calls.append((engine, keyword))
        if engine == self.fail: raise ValueError('SECRET API KEY MUST NOT LEAK')
        return fixture(engine)

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))

    def test_engine_failure_never_becomes_absence_and_survives_restart(self):
        provider = FakeProvider('google'); discovery = Discovery(self.store, provider)
        run = discovery.create({'keyword': KEYWORD})
        self.assertEqual(run['status'], 'incomplete')
        self.assertEqual(run['engines']['google']['targetPresence'], 'unknown')
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn('SECRET', str(run))
        self.assertEqual(Discovery(Store(Path(self.tmp.name))).get(run['id']), run)

    def test_no_provider_does_not_create_mock_success(self):
        d = Discovery(self.store)
        with self.assertRaises(HTTPException) as e: d.create({'keyword': KEYWORD})
        self.assertEqual(e.exception.status_code, 503); self.assertEqual(d.list(), [])

    def test_first_page_only_no_ads_or_naver_blog_and_unknown_custom_domain(self):
        result = parse_response('google', KEYWORD, fixture('google'))
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['results'][1]['platform'], 'unknown')
        self.assertEqual(result['targetPresence'], 'present')
        for params in [{'start': 10}, {'q': '다른 키워드'}, {'tbm': 'isch'}]:
            data = fixture('google'); data['search_parameters'].update(params)
            with self.assertRaises(ValueError): parse_response('google', KEYWORD, data)
        data = fixture('naver'); data['search_parameters']['where'] = 'web'
        with self.assertRaises(ValueError): parse_response('naver', KEYWORD, data)

    def test_missing_schema_or_empty_does_not_prove_absence(self):
        for data in [{}, {'error': 'quota'}, {'search_metadata': {'status': 'Success'}}]:
            with self.assertRaises(ValueError): parse_response('google', KEYWORD, data)
        data = fixture('google'); data['organic_results'] = []
        self.assertEqual(parse_response('google', KEYWORD, data)['targetPresence'], 'unknown')

    def test_saved_result_only_inspection_and_evidence_retention(self):
        d = Discovery(self.store, FakeProvider()); run = d.create({'keyword': KEYWORD})
        row = run['engines']['naver']['results'][1]
        with patch('central_discovery.inspect_wordpress', return_value={'platform': 'wordpress', 'reason': 'wordpress_html_signals'}) as inspect:
            checked = d.inspect(run['id'], row['id']); inspect.assert_called_once_with(row['url'])
        self.assertEqual(checked['engines']['naver']['results'][1]['platform'], 'wordpress')
        with self.assertRaises(HTTPException): d.inspect(run['id'], 'not-a-stored-result')
        self.assertEqual(d.get(run['id'])['keyword'], KEYWORD)

    def test_public_url_validation_and_cms_signals(self):
        for url in ['javascript:alert(1)', 'https://127.0.0.1/', 'https://user:pass@example.com/', 'https://a.internal/', 'https://example.com:22/', 'https://example.com/\n']:
            self.assertIsNone(public_url(url))
        self.assertEqual(platform_for('https://x.tistory.com/1'), 'tistory')
        self.assertEqual(platform_for('https://tistory.com.evil.example/1'), 'unknown')
        p = PageSignals(); p.feed('<p>WordPress</p>'); self.assertFalse(p.wordpress)
        p.feed('<meta name="generator" content="WordPress 7.0">'); self.assertTrue(p.wordpress)

    def test_no_private_address_page_fetch(self):
        from central_discovery import inspect_wordpress
        with patch('central_discovery.public_addresses', side_effect=ValueError('private')), patch('central_discovery.build_opener') as opener:
            self.assertEqual(inspect_wordpress('https://example.com')['platform'], 'unknown')
            opener.assert_not_called()

    def test_routes_require_auth_and_csrf_and_settings_hide_key(self):
        origin = 'https://zero.example'; password = 'test-only-password-long-enough'
        cfg = Settings(origin, Path(self.tmp.name)/'api', hash_password(password), search_key='SECRET')
        self.assertNotIn('SECRET', repr(cfg))
        client = TestClient(create_app(cfg), base_url=origin); self.addCleanup(client.close)
        self.assertEqual(client.get('/api/discovery').status_code, 401)
        self.assertEqual(client.post('/api/discovery', json={'keyword': KEYWORD}).status_code, 401)
        login = client.post('/api/login', json={'password':password}, headers={'Origin':origin}).json()
        self.assertEqual(client.post('/api/discovery', json={'keyword':KEYWORD}, headers={'Origin':origin}).status_code,403)
        with patch('central_discovery.SerpProvider.search', side_effect=lambda e,k: fixture(e)):
            value = client.post('/api/discovery', json={'keyword':KEYWORD}, headers={'Origin':origin,'X-CSRF-Token':login['csrf']})
        self.assertEqual(value.status_code,200); self.assertEqual(value.json()['status'],'retrieved')
        self.assertEqual(len(client.get('/api/discovery').json()['runs']),1)

    def test_gate_and_payload_rejection(self):
        d = Discovery(self.store, FakeProvider())
        for payload in [{'keyword':''}, {'keyword':123}, {'keyword':KEYWORD,'engine':'google'}]:
            with self.assertRaises(HTTPException): d.create(payload)
        d.gate.acquire()
        try:
            with self.assertRaises(HTTPException) as e: d.create({'keyword':KEYWORD})
            self.assertEqual(e.exception.status_code,429)
        finally: d.gate.release()

if __name__ == '__main__': unittest.main()
