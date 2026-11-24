"""PBN/backlink preparation graph and manually reported outcomes, never external writes."""
import json
import uuid
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, insert, select, update
from central_store import metadata
from central_discovery import public_url,stamp
from central_keyword_bank import fields

links=Table('network_links',metadata,Column('id',Text,primary_key=True),Column('record',Text,nullable=False))

def url(value,optional=False):
    if optional and value=='':return ''
    result=public_url(value)
    if not result or urlsplit(result).scheme!='https':raise HTTPException(400,'인증정보 없는 공개 HTTPS 주소를 입력하세요.')
    return result

class Network:
    def __init__(self,store):
        self.store=store
        with store.engine.begin() as db:store.lock(db,901001);links.create(db,checkfirst=True)
    def list(self,kind=None):
        with self.store.engine.connect() as db:rows=[json.loads(v) for v in db.execute(select(links.c.record)).scalars()]
        return [r for r in rows if not kind or r['kind']==kind]
    def create(self,p):
        fields(p,('kind','originUrl','targetUrl','note'))
        if p['kind'] not in ('pbn','backlinks'):raise HTTPException(400,'대상 종류를 확인하세요.')
        origin,target=url(p['originUrl']),url(p['targetUrl'])
        if not isinstance(p['note'],str) or len(p['note'])>5000:raise HTTPException(400,'메모는 5000자 이내입니다.')
        with self.store.engine.begin() as db:
            self.store.lock(db,901040)
            rows=[json.loads(v) for v in db.execute(select(links.c.record)).scalars()]
            old=next((r for r in rows if (r['kind'],r['originUrl'],r['targetUrl'])==(p['kind'],origin,target)),None)
            if old:return old
            r={'id':uuid.uuid4().hex,'kind':p['kind'],'originUrl':origin,'targetUrl':target,'note':p['note'],
               'revision':1,'status':'candidate','resultUrl':'','checkedAt':None,'externalExecuted':False,
               'inspection':None,'createdAt':stamp(),'history':[]}
            db.execute(insert(links).values(id=r['id'],record=json.dumps(r,ensure_ascii=False)));return r
    def edit(self,key,p):
        fields(p,('revision','status','note','resultUrl'))
        if p['status'] not in ('candidate','reviewing','ready','excluded','manual_recorded') or not isinstance(p['note'],str) or len(p['note'])>5000:
            raise HTTPException(400,'상태·메모를 확인하세요.')
        result=url(p['resultUrl'],optional=True)
        if p['status']=='manual_recorded' and not result:raise HTTPException(400,'직접 등록한 결과 URL이 필요합니다.')
        with self.store.engine.begin() as db:
            self.store.lock(db,901040)
            raw=db.execute(select(links.c.record).where(links.c.id==key)).scalar_one_or_none()
            if raw is None:raise HTTPException(404,'후보가 없습니다.')
            r=json.loads(raw)
            if type(p['revision']) is not int or r['revision']!=p['revision']:raise HTTPException(409,'다른 창에서 변경했습니다. 입력을 유지하고 다시 확인하세요.')
            old={k:r[k] for k in ('status','note','resultUrl','revision')}
            r.update(status=p['status'],note=p['note'],resultUrl=result,revision=r['revision']+1,inspection=None,checkedAt=None)
            r['history']=(r['history']+[{'before':old,'at':stamp(),'mode':'owner_manual_report'}])[-100:]
            db.execute(update(links).where(links.c.id==key).values(record=json.dumps(r,ensure_ascii=False)));return r


def classify_inspection(http_status,hrefs,origin_url,observed_at):
    """Pure parser contract for a future injected, bounded fetcher; HTTP 200 is not link proof."""
    if http_status in (404,410):state='missing_page'
    elif http_status in (401,403):state='access_denied'
    elif http_status!=200 or not isinstance(hrefs,list):state='unverified'
    else:state='link_found' if origin_url in hrefs else 'link_not_observed'
    return {'state':state,'httpStatus':http_status,'checkedAt':observed_at,'mode':'inspection_evidence','rankingEffectVerified':False}
