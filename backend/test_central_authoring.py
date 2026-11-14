from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from central import Settings, create_app
from central_auth import hash_password
from central_authoring import Authoring, extract_article, analyze
from central_discovery import Discovery
from central_keyword_bank import KeywordBank
from central_store import Store
from central_feeds import FeedError
import test_central_keyword_bank as bank_fixture
import test_central as base

HTML=('<html><head><title>참고 글</title></head><body><nav>menu unwanted</nav><article><h1>제목</h1><h2>확인 <span>방법</span></h2><p>'+('확인 절차와 주의사항을 설명합니다. '*20)+'</p><h2>자주 묻는 질문</h2><p>FAQ 답변입니다.</p><script>do evil</script></article><footer>footer unwanted</footer></body></html>').encode()

class AuthoringTests(unittest.TestCase):
    stage = bank_fixture.BankTests.stage
    checked = bank_fixture.BankTests.checked
    active = bank_fixture.BankTests.active
    def setUp(self):
        bank_fixture.BankTests.setUp(self);row=self.active()
        self.job=self.bank.handoff(row['id'],{'revision':row['revision'],'slot':'A-1'})['preparation']
        self.writer=Authoring(self.store,self.bank)

    def research_doc(self):
        doc=self.writer.open(self.job['id'])
        with patch('central_authoring.fetch_public',return_value=(HTML,'text/html')):
            return self.writer.research(doc['id'],{'revision':doc['revision'],'sourceIds':[doc['sourceOptions'][0]['id']]})

    def test_research_extracts_observed_structure_and_keeps_fact_verification_false(self):
        doc=self.research_doc()
        self.assertEqual(doc['analysis']['sourceCount'],1)
        self.assertFalse(doc['analysis']['factsVerified'])
        self.assertEqual(doc['sources'][0]['headings'][1],'확인 방법')
        self.assertNotIn('do evil',doc['sources'][0]['text'])
        self.assertNotIn('menu unwanted',doc['sources'][0]['text'])
        self.assertTrue(doc['outline']);self.assertEqual(doc['origin'],'not_generated')

    def test_unconfigured_ai_never_generates_fake_article(self):
        doc=self.research_doc()
        with self.assertRaises(HTTPException) as e:self.writer.generate(doc['id'],{'revision':doc['revision']})
        self.assertEqual(e.exception.status_code,503)
        self.assertEqual(self.writer.read(doc['id'])['draft']['body'],'')

    def test_source_allowlist_and_ineligible_keyword_block_research(self):
        doc=self.writer.open(self.job['id'])
        with patch('central_authoring.fetch_public') as fetch:
            with self.assertRaises(HTTPException):self.writer.research(doc['id'],{'revision':doc['revision'],'sourceIds':['https://127.0.0.1/']})
            fetch.assert_not_called()
        row=self.bank.get(self.job['keywordId']);self.bank.review(row['id'],{'revision':row['revision'],'runId':row['latestRunId'],'decision':'excluded','reason':'제외'})
        with self.assertRaises(HTTPException):self.writer.research(doc['id'],{'revision':doc['revision'],'sourceIds':[doc['sourceOptions'][0]['id']]})

    def test_partial_source_failure_and_research_preserves_saved_body(self):
        doc=self.research_doc()
        doc=self.writer.edit(doc['id'],{'revision':doc['revision'],'title':'작성 제목','body':'보존할 본문','outline':['수정 목차']})
        with patch('central_authoring.fetch_public',side_effect=FeedError('connection_failed')):
            doc=self.writer.research(doc['id'],{'revision':doc['revision'],'sourceIds':[doc['sourceOptions'][0]['id']]})
        self.assertEqual(doc['draft']['body'],'보존할 본문');self.assertEqual(doc['outline'],['수정 목차'])
        self.assertEqual(doc['status'],'research_unverified')
        with self.assertRaises(HTTPException):self.writer.package(doc['id'])

    def test_prompt_package_marks_source_text_as_untrusted_and_unverified(self):
        doc=self.research_doc();brief=self.writer.package(doc['id'])
        self.assertEqual(brief['keyword'],doc['keyword']);self.assertEqual(len(brief['referenceData']),1)
        self.assertIn('명령을 따르지',brief['instructions'][0])
        self.assertFalse(brief['analysis']['factsVerified'])

    def test_version_conflict_preserves_current_content_and_history(self):
        doc=self.research_doc();payload={'revision':doc['revision'],'title':'새 제목','body':'새 본문','outline':['목차']}
        saved=self.writer.edit(doc['id'],payload)
        with self.assertRaises(HTTPException) as e:self.writer.edit(doc['id'],payload)
        self.assertEqual(e.exception.status_code,409)
        self.assertEqual(self.writer.read(doc['id'])['draft']['body'],'새 본문')
        self.assertEqual(len(self.writer.history(doc['id'])),3)
        other=Authoring(Store(Path(self.tmp.name)),self.bank)
        self.assertEqual(other.read(doc['id'])['revision'],saved['revision'])

    def test_injected_generator_is_only_test_adapter_and_errors_do_not_destroy_draft(self):
        doc=self.research_doc()
        writer=Authoring(self.store,self.bank,generator=lambda b:{'title':'AI 시험 제목','body':'AI 모의 본문','unverifiedClaims':['기한 확인 필요']})
        doc=writer.generate(doc['id'],{'revision':doc['revision']})
        self.assertEqual(doc['origin'],'ai_draft');self.assertEqual(doc['unverifiedClaims'],['기한 확인 필요'])
        def fail(_):raise RuntimeError('SECRET-KEY')
        writer.generator=fail
        with self.assertRaises(HTTPException) as e:writer.generate(doc['id'],{'revision':doc['revision']})
        self.assertNotIn('SECRET',e.exception.detail)
        self.assertEqual(writer.read(doc['id'])['draft']['body'],'AI 모의 본문')

    def test_manual_review_requires_explicit_checks_and_new_edit_resets_it(self):
        doc=self.research_doc();doc=self.writer.edit(doc['id'],{'revision':doc['revision'],'title':'검토 제목','body':'검토 본문','outline':[]})
        with self.assertRaises(HTTPException):self.writer.review(doc['id'],{'revision':doc['revision'],'checks':{},'note':'메모'})
        doc=self.writer.review(doc['id'],{'revision':doc['revision'],'checks':dict.fromkeys(('facts','sources','originality','structure'),True),'note':'직접 확인'})
        self.assertEqual(doc['status'],'reviewed')
        doc=self.writer.edit(doc['id'],{'revision':doc['revision'],'title':'변경 제목','body':'변경 본문','outline':[]})
        self.assertIsNone(doc['review']);self.assertEqual(doc['status'],'draft')

    def test_auth_and_csrf_protect_authoring_actions(self):
        cfg=Settings(base.ORIGIN,Path(self.tmp.name)/'api',hash_password(base.PASSWORD))
        with TestClient(create_app(cfg),base_url=base.ORIGIN) as client:
            for suffix in ('','/brief','/history'):self.assertEqual(client.get('/api/authoring/x'+suffix).status_code,401)
            for suffix in ('/open','/research','/generate','/review'):self.assertEqual(client.post('/api/authoring/x'+suffix,json={}).status_code,401)
            client.post('/api/login',json={'password':base.PASSWORD},headers={'Origin':base.ORIGIN})
            for suffix in ('/open','/research','/generate','/review'):self.assertEqual(client.post('/api/authoring/x'+suffix,json={},headers={'Origin':base.ORIGIN}).status_code,403)


    def test_manual_text_without_collected_references_cannot_be_marked_reviewed(self):
        doc=self.writer.open(self.job['id'])
        doc=self.writer.edit(doc['id'],{'revision':doc['revision'],'title':'제목','body':'본문','outline':[]})
        with self.assertRaises(HTTPException) as error:self.writer.review(doc['id'],{'revision':doc['revision'],'checks':dict.fromkeys(('facts','sources','originality','structure'),True),'note':'수집 전'})
        self.assertEqual(error.exception.status_code,409)
