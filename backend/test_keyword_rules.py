import unittest
from keyword_rules import volume_tier, evaluate

class RulesTests(unittest.TestCase):
    def record(self, n=500):
        return {'searchVolume':{'naver':{'monthly':n,'source':'수동 확인','checkedAt':'2026-11-18T00:00:00Z'},'google':{'monthly':100000}},
                'evidence':{'engines':{'naver':{'status':'retrieved','page':1,'results':[]},'google':{'status':'retrieved','page':1,'results':[{'platform':'tistory','url':'https://one.tistory.com/1'}]}}}}
    def test_boundaries(self):
        self.assertEqual([volume_tier(n) for n in (0,499,500,2999,3000,9999,10000)], [None,None,1,1,2,2,3])
    def test_unknown_or_invalid_not_zero(self):
        for n in (None,True,'500',500.5):
            r=evaluate(self.record(n));self.assertFalse(r['eligible']);self.assertIsNone(r['naverMonthly']);self.assertIn('네이버 월간 검색량 미확인',r['reasons'])
    def test_google_volume_cannot_rescue_below_threshold(self):
        self.assertFalse(evaluate(self.record(499))['eligible'])
    def test_either_engine_target_suffices_but_both_queries_required(self):
        row=self.record();self.assertTrue(evaluate(row)['eligible']);row['evidence']['engines']['naver']['status']='failed';self.assertFalse(evaluate(row)['eligible'])
    def test_page_two_and_naver_blog_never_qualify(self):
        row=self.record();row['evidence']['engines']['google']['page']=2;self.assertFalse(evaluate(row)['eligible'])
        row=self.record();row['evidence']['engines']['google']['results'][0]['platform']='naver-blog';self.assertFalse(evaluate(row)['eligible'])
    def test_claim_without_target_evidence_cannot_qualify(self):
        row=self.record();row['evidence']['engines']['google'].update(results=[],targetPresence='present');self.assertFalse(evaluate(row)['eligible'])
    def test_explicit_manual_exclusion_persists(self):
        row=self.record();row['manualExclusion']=True;self.assertFalse(evaluate(row)['eligible'])
