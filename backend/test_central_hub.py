import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from central import Settings, create_app
from central_auth import hash_password
from central_hub import Hub

class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.encoded=hash_password('test-only-long-password')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg=Settings('https://zero.example',Path(self.tmp.name),self.encoded)
        self.app=create_app(self.cfg);self.client=TestClient(self.app,base_url=self.cfg.origin);self.addCleanup(self.client.close)
    def login(self):
        r=self.client.post('/api/login',json={'password':'test-only-long-password'},headers={'Origin':self.cfg.origin})
        return {'Origin':self.cfg.origin,'X-CSRF-Token':r.json()['csrf']}
    def test_owner_and_csrf_required(self):
        self.assertEqual(self.client.get('/api/hub/progress').status_code,401)
        h=self.login()
        self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':{}}).status_code,403)
        self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':{}},headers=h).status_code,200)
    def test_completion_requires_verification_and_conflict_preserves_data(self):
        h=self.login();data={'S01-C01':{'status':'done','note':'검증 기록','verify':[True,False]}}
        self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':data},headers=h).status_code,400)
        data['S01-C01']['verify']=[True,True]
        self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':data},headers=h).status_code,200)
        self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':{}},headers=h).status_code,409)
        self.assertEqual(self.client.get('/api/hub/progress').json()['data'],data)
        restarted=create_app(self.cfg)
        self.assertEqual(Hub(restarted.state.store).get('progress')['data'],data)
    def test_settings_validate_urls_and_remain_separate_from_workspace(self):
        h=self.login();data={'sites':'https://one.example 메모','original':'','language':'한국어','interval':'','notes':'운영 기준'}
        self.assertEqual(self.client.put('/api/hub/pbn',json={'revision':0,'data':data},headers=h).status_code,200)
        data['original']='javascript:alert(1)'
        self.assertEqual(self.client.put('/api/hub/pbn',json={'revision':1,'data':data},headers=h).status_code,400)
        self.assertEqual(self.client.get('/api/hub/pbn').json()['revision'],1)
        self.assertIsNone(self.client.get('/api/workspace').json()['data'])
    def test_unknown_fields_and_ids_do_not_write(self):
        h=self.login()
        for data in ({'S13-C01':{'status':'todo','note':'','verify':[False,False]}},{'S01-C01':{'status':'todo','note':'','verify':[True,'yes']}}):
            self.assertEqual(self.client.put('/api/hub/progress',json={'revision':0,'data':data},headers=h).status_code,400)
        self.assertEqual(self.client.get('/api/hub/progress').json()['revision'],0)
