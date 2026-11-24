"""Version-bound original-article draft adapter. No production transport is installed."""
import json
import hashlib
from fastapi import HTTPException
from sqlalchemy import Column,Table,Text,select,insert,update
from central_store import metadata
from central_discovery import stamp

transfers=Table('original_draft_transfers',metadata,Column('id',Text,primary_key=True),Column('record',Text,nullable=False))

class ArticleDrafts:
    def __init__(self,store,authoring,transport=None):
        self.store,self.authoring,self.transport=store,authoring,transport
        with store.engine.begin() as db:store.lock(db,901001);transfers.create(db,checkfirst=True)
    def read(self,key):
        with self.store.engine.connect() as db:raw=db.execute(select(transfers.c.record).where(transfers.c.id==key)).scalar_one_or_none()
        return json.loads(raw) if raw else None
    def write(self,r):
        with self.store.engine.begin() as db:
            self.store.lock(db,901060)
            db.execute(update(transfers).where(transfers.c.id==r['id']).values(record=json.dumps(r,ensure_ascii=False)))
        return r
    def submit(self,key,revision):
        if self.transport is None:raise HTTPException(503,'원본 초안 전송 어댑터 미연결 · 전송하지 않았습니다.')
        self.authoring.context(key);doc=self.authoring.read(key)
        if type(revision) is not int or doc['revision']!=revision or doc['status']!='reviewed':raise HTTPException(409,'최신 문서와 수동 검토 완료를 확인하세요.')
        identity=hashlib.sha256(json.dumps([key,revision,doc['siteUrl'],doc['draft']],sort_keys=True).encode()).hexdigest()
        with self.store.engine.begin() as db:
            self.store.lock(db,901060)
            raw=db.execute(select(transfers.c.record).where(transfers.c.id==identity)).scalar_one_or_none()
            if raw:return json.loads(raw) # Known/unknown prior attempts never issue another POST.
            r={'id':identity,'documentId':key,'documentRevision':revision,'siteUrl':doc['siteUrl'],
               'state':'intent','postId':None,'createdAt':stamp(),'checkedAt':None}
            db.execute(insert(transfers).values(id=identity,record=json.dumps(r,ensure_ascii=False)))
        try:
            remote=self.transport('create_draft',{'siteUrl':doc['siteUrl'],'title':doc['draft']['title'],'bodyMarkdown':doc['draft']['body'],'status':'draft','requestId':identity})
            if not isinstance(remote,dict) or type(remote.get('id')) is not int or remote['id']<=0:raise ValueError()
            r.update(postId=remote['id'],state='readback_pending');self.write(r)
            return self.check(identity)
        except Exception:
            latest=self.read(identity);latest['state']='unknown';self.write(latest)
            raise HTTPException(502,'원본 초안 결과 불확실 · 새 글을 자동 생성하지 않습니다. 알려진 ID만 재조회하세요.') from None
    def check(self,identity):
        r=self.read(identity)
        if r is None:raise HTTPException(404,'전송 기록이 없습니다.')
        if self.transport is None or r['postId'] is None:raise HTTPException(409,'전송 연결 또는 글 ID 미확인 · 자동 재전송하지 않습니다.')
        try:
            remote=self.transport('read_draft',{'siteUrl':r['siteUrl'],'postId':r['postId']})
            if remote.get('id')!=r['postId'] or remote.get('status')!='draft':raise ValueError()
        except Exception:raise HTTPException(502,'원본 초안 재조회 미확인 · 전송 기록 유지') from None
        r.update(state='draft_confirmed',checkedAt=stamp());return self.write(r)
