import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import insert
from central import Settings, create_app
from central_auth import hash_password
from central_store import Store
from central_discovery import Discovery
from central_feeds import FeedCollector, parse_feed
from central_keyword_bank import KeywordBank, keyword_id, next_month, keywords
import test_central as base

KW='카카오택시 분실물 조회'
BLOG='https://blog.example/'
RSS=f'<rss><channel><item><title>{KW}</title><link>{BLOG}1</link><category>택시</category></item></channel></rss>'.encode()

class Provider:
    fail = None
    unknown = False
    def search(self, engine, keyword):
        if engine == self.fail: raise TimeoutError()
        return {'search_metadata': {'status':'Success'}, 'search_parameters':{'engine':engine,'q' if engine == 'google' else 'query':keyword},
                'organic_results' if engine == 'google' else 'web_results':[{'position':1,'title':'글','link':'https://unknown.example/1' if self.unknown else 'https://one.tistory.com/1'}]}

class BankTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))
        self.provider=Provider();self.discovery=Discovery(self.store,self.provider)
        self.bank=KeywordBank(self.store,self.discovery)
        self.feeds=FeedCollector(self.store)
        with patch('central_feeds.collect_blog',return_value={'feedUrl':BLOG+'feed/',**parse_feed(RSS,BLOG+'feed/',BLOG)}):
            self.collection=self.feeds.create({'blogUrl':BLOG})
        self.store.save(0,copy.deepcopy(base.DATA))

    def stage(self, text=KW):
        return self.bank.stage({'collectionId':self.collection['id'],'selections':[{'index':0,'keyword':text}]})['keywords'][0]

    def checked(self):
        row=self.stage()
        return self.bank.check(row['id'],{'revision':row['revision']})

    def active(self):
        row=self.checked()
        return self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'active','reason':'출처 확인 후 선택'})

    def test_unreviewed_candidates_are_not_active_and_need_both_engines(self):
        row=self.stage()
        self.assertEqual(row['status'],'pending');self.assertIsNone(row['searchVolume'])
        with self.assertRaises(HTTPException):self.bank.review(row['id'],{'revision':row['revision'],'runId':None,'decision':'active','reason':'선택'})
        self.provider.fail='google'
        row=self.bank.check(row['id'],{'revision':row['revision']})
        self.assertEqual(row['verification'],'incomplete')
        with self.assertRaises(HTTPException):self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'active','reason':'선택'})

    def test_normalization_merges_sources_and_does_not_reactivate_excluded(self):
        row=self.active();row=self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'excluded','reason':'수동 검토 제외'})
        again=self.stage('  '+KW+'  ')
        self.assertEqual(again['id'],row['id']);self.assertEqual(again['status'],'excluded')
        self.assertEqual(len(self.bank.list()['keywords']),1)
        self.assertEqual(again['revision'],row['revision'])

    def test_original_candidate_and_custom_search_phrase_both_preserved(self):
        row=self.stage('카카오택시 분실물')
        self.assertEqual(row['sources'][0]['originalText'],KW)
        self.assertEqual(row['keyword'],'카카오택시 분실물')

    def test_stage_failure_rolls_back_entire_batch(self):
        with self.assertRaises(HTTPException):self.bank.stage({'collectionId':self.collection['id'],'selections':[{'index':0,'keyword':KW},{'index':999,'keyword':'잘못됨'}]})
        self.assertEqual(self.bank.list()['keywords'],[])

    def test_mismatched_query_stale_revision_and_unconfirmed_platform_rejected(self):
        row=self.stage();run=self.discovery.create({'keyword':'다른 키워드'})
        with self.assertRaises(HTTPException):self.bank.attach(row['id'],{'revision':row['revision'],'runId':run['id']})
        self.provider.unknown=True
        row=self.bank.check(row['id'],{'revision':row['revision']})
        with self.assertRaises(HTTPException):self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'active','reason':'선택'})
        with self.assertRaises(HTTPException) as error:self.bank.check(row['id'],{'revision':1})
        self.assertEqual(error.exception.status_code,409)

    def test_monthly_failed_check_preserves_active_original_and_regular_date(self):
        row=self.active();before=copy.deepcopy(row)
        self.provider.fail='google'
        row=self.bank.check(row['id'],{'revision':row['revision']})
        self.assertEqual(row['status'],'active');self.assertEqual(row['sources'],before['sources'])
        self.assertEqual(row['checkedAt'],before['checkedAt']);self.assertEqual(row['nextCheckAt'],before['nextCheckAt'])
        self.assertTrue(row['retryAt']);self.assertTrue(row['reviewRequired'])
        with self.assertRaises(HTTPException):self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})
        self.assertEqual(self.bank.history(row['id'])[-1]['event'],'search_unverified')

    def test_monthly_success_preserves_keyword_and_reschedules(self):
        row=self.active();row=self.bank.check(row['id'],{'revision':row['revision']})
        self.assertEqual(row['status'],'active');self.assertFalse(row['reviewRequired']);self.assertIsNone(row['retryAt'])
        self.assertEqual(row['nextCheckAt'],next_month(row['checkedAt']))
        self.assertEqual(next_month('2026-01-31T12:00:00+00:00'),'2026-02-28T12:00:00+00:00')
        self.assertEqual(next_month('2027-12-31T12:00:00+00:00'),'2028-01-31T12:00:00+00:00')

    def test_handoff_deduplicates_same_site_across_slots_and_preserves_db(self):
        row=self.active()
        first=self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})
        duplicate=self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})
        self.assertTrue(first['created']);self.assertFalse(duplicate['created'])
        data=copy.deepcopy(base.DATA);data['sites']['A-2']['url']=data['sites']['A-1']['url'];self.store.save(1,data)
        self.assertFalse(self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-2'})['created'])
        self.assertEqual(len(self.bank.list()['keywords']),1);self.assertFalse(first['preparation']['articleGenerated'])
        data['sites']['A-2']['url']='https://different.example';self.store.save(2,data)
        self.assertTrue(self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-2'})['created'])
        self.assertEqual(len(self.bank.queue()),2)

    def test_exclusion_and_site_change_block_preparations_without_deleting(self):
        row=self.active();self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})
        self.assertTrue(self.bank.queue()[0]['eligible'])
        row=self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'excluded','reason':'조건 변경'})
        self.assertFalse(self.bank.queue()[0]['eligible']);self.assertEqual(len(self.bank.history(row['id'])),5)
        row=self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'active','reason':'재검토'})
        data=copy.deepcopy(base.DATA);data['sites']['A-1']['url']='https://changed.example';self.store.save(1,data)
        self.assertFalse(self.bank.queue()[0]['eligible'])

    def test_due_recheck_is_bounded_and_failure_waits_until_retry(self):
        row=self.active();row['nextCheckAt']='2020-01-01T00:00:00+00:00'
        with self.store.engine.begin() as db: self.bank.write(db,row,'test_due')
        self.provider.fail='google'
        self.assertEqual(len(self.bank.due(1)),1)
        self.assertEqual(self.bank.due(1),[])
        with self.assertRaises(HTTPException):self.bank.due(10)

    def test_export_restart_and_pagination_keep_history(self):
        row=self.active();self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})
        other=KeywordBank(Store(Path(self.tmp.name)),self.discovery)
        export=other.export()
        self.assertEqual(export['keywords'][0]['id'],row['id']);self.assertEqual(len(export['preparations']),1)
        self.assertEqual(len(export['events']),4);self.assertIsNone(other.list()['nextOffset'])
        self.assertEqual(self.store.current()['data'],base.DATA)

    def test_all_new_routes_require_session_and_writes_require_csrf(self):
        cfg=Settings(base.ORIGIN,Path(self.tmp.name)/'api',hash_password(base.PASSWORD))
        with TestClient(create_app(cfg),base_url=base.ORIGIN) as client:
            for path in ['/api/keyword-bank','/api/keyword-bank/export','/api/article-preparations','/api/keyword-bank/x/history']:
                self.assertEqual(client.get(path).status_code,401)
            paths=['/api/keyword-bank/stage','/api/keyword-bank/x/check','/api/keyword-bank/x/review','/api/keyword-bank/x/evidence','/api/keyword-bank/x/handoff','/api/feed-collections/from-discovery']
            for path in paths:self.assertEqual(client.post(path,json={}).status_code,401)
            client.post('/api/login',json={'password':base.PASSWORD},headers={'Origin':base.ORIGIN})
            for path in paths:self.assertEqual(client.post(path,json={},headers={'Origin':base.ORIGIN}).status_code,403)

    def test_fixture_pipeline_search_to_feed_to_bank_to_handoff(self):
        # Controlled in-process pipeline test; never a live SERP/RSS/Render test.
        cfg=Settings(base.ORIGIN,Path(self.tmp.name)/'api',hash_password(base.PASSWORD),search_key='test-key-only')
        with TestClient(create_app(cfg),base_url=base.ORIGIN) as client:
            login=client.post('/api/login',json={'password':base.PASSWORD},headers={'Origin':base.ORIGIN}).json()
            headers={'Origin':base.ORIGIN,'X-CSRF-Token':login['csrf']}
            client.put('/api/workspace',json={'baseRevision':0,'data':copy.deepcopy(base.DATA)},headers=headers)
            with patch('central_discovery.SerpProvider.search',side_effect=self.provider.search):
                run=client.post('/api/discovery',json={'keyword':KW},headers=headers).json()
                result=run['engines']['google']['results'][0]
                with patch('central_feeds.collect_blog',return_value={'feedUrl':BLOG+'feed/',**parse_feed(RSS,BLOG+'feed/',BLOG)}):
                    feed=client.post('/api/feed-collections/from-discovery',json={'runId':run['id'],'resultId':result['id']},headers=headers).json()
                row=client.post('/api/keyword-bank/stage',json={'collectionId':feed['id'],'selections':[{'index':0,'keyword':KW}]},headers=headers).json()['keywords'][0]
                row=client.post('/api/keyword-bank/'+row['id']+'/check',json={'revision':row['revision']},headers=headers).json()
            row=client.post('/api/keyword-bank/'+row['id']+'/review',json={'revision':row['revision'],'runId':row['latestRunId'],'decision':'active','reason':'검토 완료'},headers=headers).json()
            response=client.post('/api/keyword-bank/'+row['id']+'/handoff',json={'revision':row['revision'],'slot':'A-1'},headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get('/api/article-preparations').json()['preparations'][0]['keyword'],KW)
            self.assertEqual(client.get('/api/keyword-bank').json()['keywords'][0]['status'],'active')
