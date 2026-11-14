import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from central import Settings, create_app
from central_auth import hash_password
from central_store import Store
from central_discovery import Discovery, runs
from central_feeds import FeedCollector, collections
from central_keyword_bank import KeywordBank, events
from central_activity import activity
import test_central as base

class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))
        self.discovery=Discovery(self.store)
        FeedCollector(self.store);KeywordBank(self.store,self.discovery)

    def add_search(self, id, status='incomplete'):
        row={'id':id,'createdAt':'2026-11-14T00:00:00+00:00','keyword':'카카오택시 분실물 조회','status':status,'engines':{'naver':{'status':'retrieved','targetPresence':'present'},'google':{'status':'unverified','targetPresence':'unknown'}}}
        with self.store.engine.begin() as db:db.execute(insert(runs).values(id=id,created_at=row['createdAt'],record=json.dumps(row)))

    def test_empty_history_is_confirmed_empty_without_writes_or_network(self):
        with patch('central_discovery.SerpProvider.search',side_effect=AssertionError('no search')),patch('central_feeds.fetch_public',side_effect=AssertionError('no fetch')):
            result=activity(self.store)
        self.assertEqual(result['counts'],{'records':0,'attention':0,'review':0})
        self.assertEqual(result['items'],[]);self.assertFalse(result['hasEarlierRecords'])
        self.assertEqual(self.store.current()['revision'],0)

    def test_partial_search_is_attention_and_never_success(self):
        self.add_search('r')
        result=activity(self.store)
        self.assertEqual(result['items'][0]['state'],'attention')
        self.assertEqual(result['counts']['attention'],1)
        self.assertEqual(result['items'][0]['target'],'discovery')
        self.assertNotIn('완료',result['items'][0]['label'].replace('미완료',''))

    def test_pending_does_not_claim_live_worker_running(self):
        self.add_search('p','pending')
        item=activity(self.store)['items'][0]
        self.assertEqual(item['label'],'검색 결과 미확정')
        self.assertIn('중단',item['message'])

    def test_feed_failure_uses_allowlisted_reason_never_raw_error(self):
        with self.store.engine.begin() as db:
            db.execute(insert(collections).values(id='f',created_at='2026-11-14T01:00:00+00:00',record=json.dumps({'blogUrl':'https://example.com','status':'unverified','reason':'SECRET-token-provider-error','posts':[],'candidates':[]})))
        result=activity(self.store)
        self.assertNotIn('SECRET',json.dumps(result));self.assertEqual(result['items'][0]['target'],'feeds')

    def test_handoff_is_only_preparation_and_original_tables_unchanged(self):
        bank=KeywordBank(self.store,self.discovery)
        with self.store.engine.begin() as db:bank.event(db,'key','original_article_handoff',{'privateNote':'DO-NOT-EXPOSE'})
        before=bank.export();result=activity(self.store);after=bank.export()
        self.assertEqual(before['events'],after['events'])
        self.assertEqual(result['items'][0]['stage'],6)
        self.assertIn('실제 AI 글',result['items'][0]['message'])
        self.assertNotIn('DO-NOT-EXPOSE',json.dumps(result))

    def test_bounded_scope_reports_earlier_records(self):
        for i in range(25):self.add_search(str(i))
        result=activity(self.store)
        self.assertEqual(len(result['items']),20);self.assertTrue(result['hasEarlierRecords'])
        self.assertEqual(result['scope'],'latest_20_per_source')

    def test_corrupt_source_is_not_silently_shown_as_complete_zero(self):
        self.add_search('valid')
        with self.store.engine.begin() as db:db.execute(insert(collections).values(id='bad',created_at='2026-11-14',record='bad json'))
        result=activity(self.store)
        self.assertEqual(result['incompleteSources'],['rss']);self.assertEqual(len(result['items']),1)

    def test_authentication_required_and_only_read_route_exists(self):
        cfg=Settings(base.ORIGIN,Path(self.tmp.name)/'api',hash_password(base.PASSWORD))
        with TestClient(create_app(cfg),base_url=base.ORIGIN) as client:
            self.assertEqual(client.get('/api/activity').status_code,401)
            client.post('/api/login',json={'password':base.PASSWORD},headers={'Origin':base.ORIGIN})
            self.assertEqual(client.get('/api/activity').status_code,200)
            self.assertEqual(client.get('/api/activity').headers['cache-control'],'no-store')
            self.assertEqual(client.post('/api/activity',json={}).status_code,405)
