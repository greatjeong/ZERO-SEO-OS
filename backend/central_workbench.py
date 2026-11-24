"""Owner-only development workbench. Safe preparation and explicit isolated rehearsal."""
import json
import uuid
from fastapi import HTTPException
from sqlalchemy import Column,Table,Text,select,insert,update
from central_store import metadata
from central_discovery import stamp
from central_keyword_bank import fields
from central_adapters import GenerationAdapter,VolumeAdapter,quality_report,text
from keyword_rules import evaluate

settings=Table('operation_settings',metadata,Column('id',Text,primary_key=True),Column('record',Text,nullable=False))
DEFAULT={'aiProvider':'','aiModel':'','maxOutputChars':50000,'volumeProvider':'','notes':''}

class Workbench:
    def __init__(self,store,bank,authoring):
        from central_jobs import Jobs
        from central_network import Network
        from central_backups import Backups
        from central_publish import ArticleDrafts
        self.store,self.bank,self.authoring=store,bank,authoring
        self.jobs=Jobs(store);self.network=Network(store);self.backups=Backups(store);self.article_drafts=ArticleDrafts(store,authoring)
        with store.engine.begin() as db:store.lock(db,901001);settings.create(db,checkfirst=True)
    def config(self):
        with self.store.engine.connect() as db:raw=db.execute(select(settings.c.record).where(settings.c.id=='providers')).scalar_one_or_none()
        return json.loads(raw) if raw else {'revision':0,'data':dict(DEFAULT)}
    def save_config(self,p):
        fields(p,('revision','data'));d=p['data']
        if not isinstance(d,dict) or set(d)!=set(DEFAULT) or type(d['maxOutputChars']) is not int or not 100<=d['maxOutputChars']<=50000:raise HTTPException(400,'연결 준비 설정 형식을 확인하세요.')
        for key in ('aiProvider','aiModel','volumeProvider','notes'):
            text(d[key],1000 if key=='notes' else 100,True)
            if any(token in d[key].lower() for token in ('sk-','api_key=','bearer ','postgresql://')):raise HTTPException(400,'이 화면에는 비밀번호·API 키를 저장하지 마세요.')
        with self.store.engine.begin() as db:
            self.store.lock(db,901050)
            raw=db.execute(select(settings.c.record).where(settings.c.id=='providers')).scalar_one_or_none();old=json.loads(raw) if raw else {'revision':0}
            if type(p['revision']) is not int or old['revision']!=p['revision']:raise HTTPException(409,'설정이 변경됐습니다. 입력을 보관하고 다시 불러오세요.')
            row={'revision':old['revision']+1,'data':d,'updatedAt':stamp()}
            query=update(settings).where(settings.c.id=='providers') if raw else insert(settings).values(id='providers')
            db.execute(query.values(record=json.dumps(row,ensure_ascii=False)))
        return row
    def snapshot(self):
        from central_authoring import documents
        with self.store.engine.connect() as db:docs=[json.loads(v) for v in db.execute(select(documents.c.record)).scalars()]
        return {'config':self.config(),'jobs':self.jobs.list(),'links':self.network.list(),
                'documents':[{'id':d['id'],'title':d['draft']['title'] or d['keyword']} for d in docs],
                'keywords':[{'id':d['id'],'title':d['keyword']} for d in self.bank.list(0)['keywords']],
                'connections':{'ai':False,'volume':False,'publishing':False,'networkExecution':False},
                'mode':'preparation_only','note':'설정 저장·작업 준비·모의 검증입니다. 실제 외부 실행은 켜지지 않습니다.'}
    def enqueue(self,p):
        fields(p,('kind','target'))
        if p['kind']=='authoring':self.authoring.context(p['target']);self.authoring.read(p['target'])
        elif p['kind']=='recheck':self.bank.get(p['target'])
        elif p['kind'] in ('pbn','backlinks'):
            if not any(r['id']==p['target'] and r['kind']==p['kind'] for r in self.network.list()):raise HTTPException(404,'연결된 후보를 먼저 등록하세요.')
        else:raise HTTPException(400,'작업 종류를 확인하세요.')
        return self.jobs.enqueue(p['kind'],p['target'])
    def rehearse(self):
        job=self.jobs.enqueue('diagnostic',uuid.uuid4().hex,'rehearsal')
        return self.jobs.run(job['id'],lambda _:rehearsal(self.config()['data']['maxOutputChars']))


def rehearsal(max_chars=50000):
    """Synthetic example.com fixtures use real policy and adapter validation, no HTTP calls."""
    at=stamp();keyword='모의 검증 키워드';stages=[]
    def add(name,evidence):stages.append({'name':name,'status':'passed','evidence':evidence,'mode':'synthetic_rehearsal'})
    engines={k:{'status':'retrieved','page':1,'results':[{'platform':'wordpress','url':'https://example.com/reference'}]} for k in ('naver','google')}
    add('양쪽 검색 응답 계약','예시 네이버·구글 1페이지 응답')
    vol=VolumeAdapter(lambda q:{'keyword':q,'monthly':500,'source':'synthetic-fixture','checkedAt':at}).lookup(keyword)
    row={'searchVolume':{'naver':{'monthly':vol['monthly'],'source':vol['source'],'checkedAt':at}},'evidence':{'engines':engines},'verification':'both_retrieved'}
    policy=evaluate(row)
    if not policy['eligible']:raise ValueError('fixture policy failed')
    add('검색량·선별 규칙',{'eligible':True,'tier':policy['tier'],'monthly':vol['monthly']})
    from central_feeds import parse_feed
    feed=parse_feed(('<rss><channel><item><title>'+keyword+'</title><link>https://example.com/reference</link></item></channel></rss>').encode(),'https://example.com/feed','https://example.com/')
    if not feed['candidates'] or feed['candidates'][0]['searchVerification']!='not_checked':raise ValueError('RSS contract failed')
    add('RSS 후보→작성 준비 계약',{'source':feed['candidates'][0]['sources'][0]['feedUrl'],'candidateCount':len(feed['candidates']),'originalRetained':True})
    writer=GenerationAdapter(lambda _:{'title':'모의 원고','body':'## 핵심 답변\n이 내용은 기능 검증용 예시입니다.','unverifiedClaims':['실제 사실 확인 전 예시']},max_chars)
    draft=writer({'keyword':keyword,'referenceData':[{'text':'신뢰되지 않은 예시 자료'}]})
    quality=quality_report({'draft':draft,'sources':[{'status':'collected'}],'unverifiedClaims':draft['unverifiedClaims']})
    add('AI 응답·편집 검수 계약',{'characters':quality['charactersWithoutWhitespace'],'factsVerified':False})
    add('WP 초안 결과 계약',{'status':'draft','postId':'synthetic-not-a-real-post','published':False})
    from central_network import classify_inspection
    add('PBN·백링크 점검 계약',classify_inspection(200,['https://example.com/original'],'https://example.com/original',at))
    return {'mode':'synthetic_rehearsal','stages':stages,'externalExecuted':False,'realArticleGenerated':False,
            'note':'형식·정책 연결을 확인한 모의 자료입니다. 실제 검색·RSS 수집·AI 생성·WP 발행·링크 등록 성공이 아닙니다.'}
