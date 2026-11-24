import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.dialects import postgresql
from central import Settings,create_app
from central_auth import hash_password
from central_store import Store
from central_authoring import Authoring,documents
from central_workbench import Workbench,rehearsal
from central_adapters import GenerationAdapter,VolumeAdapter,quality_report
from central_network import classify_inspection
from central_jobs import jobs,Jobs
from central_publish import ArticleDrafts
from central_backups import checksum
import test_central_keyword_bank as fixture
from test_central_authoring import HTML

class WorkbenchTests(unittest.TestCase):
    stage=fixture.BankTests.stage
    checked=fixture.BankTests.checked
    active=fixture.BankTests.active
    def setUp(self):
        fixture.BankTests.setUp(self)
        from central_hub import Hub
        from central_feeds import FeedCollector
        Hub(self.store);FeedCollector(self.store)
        kw=self.active();self.prep=self.bank.handoff(kw['id'],{'revision':kw['revision'],'slot':'A-1'})['preparation']
        self.author=Authoring(self.store,self.bank);self.w=Workbench(self.store,self.bank,self.author)
    def article(self):
        doc=self.author.open(self.prep['id'])
        with patch('central_authoring.fetch_public',return_value=(HTML,'text/html')):
            return self.author.research(doc['id'],{'revision':doc['revision'],'sourceIds':[doc['sourceOptions'][0]['id']]})
    def edit(self,doc,body='수정 본문'):
        return self.author.edit(doc['id'],{'revision':doc['revision'],'title':'새 원본 제목','body':body,'outline':['새 목차']})
    def test_version_compare_restore_preserves_history_and_cas(self):
        a=self.article();b=self.edit(a,'첫 저장 본문');c=self.edit(b,'두 번째 본문')
        compared=self.author.compare(c['id'],b['revision']);self.assertIn('첫 저장 본문',compared['diff']);self.assertEqual(self.author.read(c['id'])['revision'],c['revision'])
        restored=self.author.restore(c['id'],{'revision':c['revision'],'sourceRevision':b['revision']})
        self.assertEqual(restored['draft']['body'],'첫 저장 본문');self.assertIsNone(restored['review'])
        self.assertEqual(len(self.author.history(c['id'])),5)
        with self.assertRaises(HTTPException):self.author.restore(c['id'],{'revision':c['revision'],'sourceRevision':b['revision']})
        self.assertEqual(self.author.export(c['id'])['document']['revision'],restored['revision'])
    def test_quality_is_transparent_and_never_fact_verification(self):
        d=self.edit(self.article(),'같은 긴 문단입니다. '*10+'\n'+'같은 긴 문단입니다. '*10)
        q=self.author.quality(d['id']);self.assertFalse(q['factsVerified']);self.assertIn('repeated_paragraph',[f['code'] for f in q['findings']])
    def test_contracts_reject_wrong_keyword_noninteger_and_invalid_generation(self):
        for monthly in ('< 10',True,-1):
            with self.assertRaises(HTTPException):VolumeAdapter(lambda k:{'keyword':k,'monthly':monthly,'source':'mock','checkedAt':'2026-11-24T00:00:00Z'}).lookup('시험')
        with self.assertRaises(HTTPException):VolumeAdapter(lambda k:{'keyword':'다른검색어','monthly':500,'source':'mock','checkedAt':'2026-11-24T00:00:00Z'}).lookup('시험')
        with self.assertRaises(HTTPException):GenerationAdapter(lambda _: {'title':'가','body':'a'*101},100)({})
        def leak(_):raise Exception('sk-SECRET')
        with self.assertRaises(HTTPException) as e:GenerationAdapter(leak)({})
        self.assertNotIn('SECRET',e.exception.detail)
    def test_config_cas_never_enables_external_connections(self):
        c=self.w.config();c['data']['aiProvider']='연결 예정';saved=self.w.save_config(c)
        self.assertEqual(saved['revision'],1);self.assertFalse(any(self.w.snapshot()['connections'].values()))
        with self.assertRaises(HTTPException):self.w.save_config(c)
        saved['data']['aiModel']='sk-secret'
        with self.assertRaises(HTTPException):self.w.save_config({'revision':1,'data':saved['data']})
    def test_queue_duplicate_and_state_guards_retry_limit(self):
        j=self.w.jobs.enqueue('diagnostic','fixture','rehearsal');self.assertEqual(self.w.jobs.enqueue('diagnostic','fixture','rehearsal')['id'],j['id'])
        p=self.w.jobs.action(j['id'],j['revision'],'pause');self.assertIsNone(self.w.jobs.claim(j['id']))
        q=self.w.jobs.action(j['id'],p['revision'],'resume')
        def fail(_):raise RuntimeError('private provider error')
        for attempt in range(3):
            q=self.w.jobs.run(j['id'],fail);self.assertEqual(q['attempts'],attempt+1)
            if attempt<2:q=self.w.jobs.action(j['id'],q['revision'],'retry')
        with self.assertRaises(HTTPException):self.w.jobs.action(j['id'],q['revision'],'retry')
        blocked=self.w.enqueue({'kind':'recheck','target':self.prep['keywordId']});self.assertIsNone(self.w.jobs.claim(blocked['id']))
    def test_concurrent_claim_only_one_worker_and_restart_stays_claimed(self):
        j=self.w.jobs.enqueue('diagnostic','concurrent','rehearsal');results=[]
        def claim():results.append(Jobs(self.store).claim(j['id']))
        threads=[threading.Thread(target=claim) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(v is not None for v in results),1)
        self.assertIsNone(Jobs(Store(Path(self.tmp.name))).claim(j['id']))
    def test_expired_claim_goes_unknown_and_cannot_auto_retry(self):
        j=self.w.jobs.enqueue('diagnostic','expire','rehearsal');r=self.w.jobs.claim(j['id']);r['leaseUntil']=0
        with self.store.engine.begin() as db:db.execute(update(jobs).where(jobs.c.id==j['id']).values(record=json.dumps(r)))
        self.assertIsNone(self.w.jobs.claim(j['id']));self.assertEqual(self.w.jobs.list()[0]['status'],'unknown')
        with self.assertRaises(HTTPException):self.w.jobs.action(j['id'],r['revision']+1,'retry')
    def test_network_duplicate_cas_and_manual_result_is_not_verified(self):
        r=self.w.network.create({'kind':'pbn','originUrl':'https://example.com/original','targetUrl':'https://pbn.example.com','note':'운영 후보'})
        self.assertEqual(self.w.network.create({'kind':'pbn','originUrl':r['originUrl'],'targetUrl':r['targetUrl'],'note':'중복'})['id'],r['id'])
        p={'revision':r['revision'],'status':'manual_recorded','resultUrl':'https://pbn.example.com/post','note':'직접 기록'}
        saved=self.w.network.edit(r['id'],p);self.assertIsNone(saved['inspection']);self.assertFalse(saved['externalExecuted'])
        with self.assertRaises(HTTPException):self.w.network.edit(r['id'],p)
        self.assertEqual(classify_inspection(200,[],r['originUrl'],'now')['state'],'link_not_observed')
        with self.assertRaises(HTTPException):self.w.network.create({'kind':'backlinks','originUrl':'https://127.0.0.1','targetUrl':'https://example.com','note':''})
    def test_application_archive_restores_to_separate_database_without_secrets(self):
        doc=self.edit(self.article());self.w.network.create({'kind':'backlinks','originUrl':'https://example.com/post','targetUrl':'https://board.example.com','note':'후보'})
        archive=self.w.backups.export();self.assertNotIn('sessions',archive['tables']);self.assertNotIn('wordpress_credentials',archive['tables']);self.assertIn('original_article_versions',archive['tables'])
        with tempfile.TemporaryDirectory() as folder:
            other=Store(Path(folder));from central_discovery import Discovery
            from central_keyword_bank import KeywordBank
            from central_feeds import FeedCollector
            from central_hub import Hub
            FeedCollector(other);Hub(other);bank=KeywordBank(other,Discovery(other));author=Authoring(other,bank);w=Workbench(other,bank,author)
            preview=w.backups.preview(archive);result=w.backups.restore({'archive':archive,'basis':preview['basis']})
            self.assertGreater(result['added'],0);self.assertEqual(author.read(doc['id'])['draft']['body'],doc['draft']['body'])
            again=w.backups.preview(archive);self.assertEqual(sum(d['add'] for d in again['details']),0)
            other.engine.dispose()
    def test_backup_conflicts_preserve_existing_and_stale_preview_rejected(self):
        d=self.edit(self.article(),'원래 본문');archive=self.w.backups.export();preview=self.w.backups.preview(archive)
        latest=self.edit(d,'현재 본문')
        with self.assertRaises(HTTPException):self.w.backups.restore({'archive':archive,'basis':preview['basis']})
        p=self.w.backups.preview(archive);self.assertGreater(sum(v['conflictsKept'] for v in p['details']),0)
        self.w.backups.restore({'archive':archive,'basis':p['basis']});self.assertEqual(self.author.read(d['id'])['draft']['body'],'현재 본문')
        archive['tables']['sessions']=[];archive['checksum']=checksum(archive['tables'])
        with self.assertRaises(HTTPException):self.w.backups.preview(archive)
    def test_rehearsal_has_no_real_calls_and_does_not_change_keyword_or_document(self):
        d=self.article();before=self.author.export(d['id']);kw=self.bank.get(self.prep['keywordId'])
        with patch('central_authoring.fetch_public',side_effect=AssertionError('network forbidden')):
            report=self.w.rehearse()
        self.assertEqual(report['status'],'succeeded');self.assertEqual(len(report['result']['stages']),6)
        self.assertFalse(report['externalExecuted']);self.assertEqual(self.author.export(d['id']),before);self.assertEqual(self.bank.get(kw['id']),kw)
    def test_mock_pipeline_uses_real_policy_edit_review_and_durable_draft_readback(self):
        d=self.article();self.author.generator=GenerationAdapter(lambda b:{'title':'모의 생성','body':'## 답변\n검증용 원고','unverifiedClaims':[]})
        d=self.author.generate(d['id'],{'revision':d['revision']})
        d=self.author.review(d['id'],{'revision':d['revision'],'checks':dict.fromkeys(('facts','sources','originality','structure'),True),'note':'모의 시험 검토'})
        calls=[]
        def wp(action,payload):
            calls.append(action)
            return {'id':123,'status':'draft'}
        sender=ArticleDrafts(self.store,self.author,wp);sent=sender.submit(d['id'],d['revision']);self.assertEqual(sent['state'],'draft_confirmed')
        sender.submit(d['id'],d['revision']);self.assertEqual(calls,['create_draft','read_draft'])
        self.assertEqual(self.author.export(d['id'])['document']['draft']['title'],'모의 생성')
    def test_uncertain_draft_does_not_post_twice(self):
        d=self.edit(self.article());d=self.author.review(d['id'],{'revision':d['revision'],'checks':dict.fromkeys(('facts','sources','originality','structure'),True),'note':'검토'})
        calls=[]
        def fail(action,p):calls.append(action);raise TimeoutError('private')
        sender=ArticleDrafts(self.store,self.author,fail)
        with self.assertRaises(HTTPException):sender.submit(d['id'],d['revision'])
        row=sender.submit(d['id'],d['revision']);self.assertEqual(row['state'],'unknown');self.assertIsNone(row['postId']);self.assertEqual(calls,['create_draft'])
    def test_postgres_new_tables_compile(self):
        from sqlalchemy.schema import CreateTable
        for table in (jobs,):self.assertIn('CREATE TABLE',str(CreateTable(table).compile(dialect=postgresql.dialect())))
    def test_all_new_endpoints_owner_and_csrf_protected(self):
        origin='https://example.com';cfg=Settings(origin,Path(self.tmp.name)/'security',hash_password('test-owner-password-123'))
        routes=[('/api/workbench/config','PUT'),('/api/workbench/rehearse','POST'),('/api/workbench/jobs','POST'),('/api/workbench/jobs/x/action','POST'),('/api/workbench/jobs/x/rehearse','POST'),('/api/workbench/network','POST'),('/api/workbench/network/x','PUT'),('/api/workbench/archive/preview','POST'),('/api/workbench/archive/restore','POST'),('/api/authoring/x/restore','POST')]
        gets=['/api/workbench','/api/workbench/archive','/api/authoring/x/export','/api/authoring/x/compare/1','/api/authoring/x/quality']
        with TestClient(create_app(cfg),base_url=origin) as c:
            for path in gets:self.assertEqual(c.get(path).status_code,401,path)
            for path,method in routes:self.assertEqual(c.request(method,path,json={}).status_code,401,path)
            login=c.post('/api/login',json={'password':'test-owner-password-123'},headers={'Origin':origin}).json()
            for path,method in routes:
                self.assertEqual(c.request(method,path,json={},headers={'Origin':origin}).status_code,403,path)
                self.assertEqual(c.request(method,path,json={},headers={'Origin':'https://other.example','X-CSRF-Token':login['csrf']}).status_code,403,path)
            self.assertEqual(c.get('/api/workbench').status_code,200)
    def test_invalid_archive_rolls_back_and_preserves_existing_store(self):
        self.article();archive=self.w.backups.export();before=self.store.current()
        archive['tables']['original_article_versions'][0]['record']='{"document": {"revision": "bad"}}';archive['checksum']=checksum(archive['tables'])
        with self.assertRaises(HTTPException):self.w.backups.preview(archive)
        self.assertEqual(self.store.current(),before)
    def test_queue_unknown_action_and_unconfigured_original_publish_stay_blocked(self):
        d=self.article();j=self.w.jobs.enqueue('diagnostic','invalid','rehearsal')
        with self.assertRaises(HTTPException):self.w.jobs.action(j['id'],j['revision'],[])
        with self.assertRaises(HTTPException):self.w.article_drafts.submit(d['id'],d['revision'])
        self.assertEqual(self.author.read(d['id'])['revision'],d['revision'])
