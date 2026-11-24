"""Durable preparation queue. Live jobs are blocked; rehearsal runners cannot publish."""
import hashlib
import json
import secrets
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, select, insert, update
from central_store import metadata
from central_discovery import stamp

jobs=Table('operation_jobs',metadata,Column('id',Text,primary_key=True),Column('record',Text,nullable=False))

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class Jobs:
    def __init__(self,store):
        self.store=store
        with store.engine.begin() as db:store.lock(db,901001);jobs.create(db,checkfirst=True)
    def _all(self,db):return [json.loads(v) for v in db.execute(select(jobs.c.record)).scalars()]
    def list(self):
        with self.store.engine.connect() as db:rows=self._all(db)
        return sorted(rows,key=lambda r:r['createdAt'],reverse=True)
    def enqueue(self,kind,target,mode='prepared'):
        if kind not in ('authoring','recheck','pbn','backlinks','diagnostic') or mode not in ('prepared','rehearsal'):
            raise HTTPException(400,'작업 종류·모드를 확인하세요.')
        if not isinstance(target,str) or not 1<=len(target)<=200:raise HTTPException(400,'작업 대상을 확인하세요.')
        fingerprint=digest([kind,target,mode])
        with self.store.engine.begin() as db:
            self.store.lock(db,901030)
            existing=next((r for r in self._all(db) if r['fingerprint']==fingerprint and r['status'] not in ('cancelled',)),None)
            if existing:return existing
            r={'id':uuid.uuid4().hex,'fingerprint':fingerprint,'kind':kind,'target':target,'mode':mode,
               'status':'queued' if mode=='rehearsal' else 'blocked','revision':1,'attempts':0,'maxAttempts':3,
               'createdAt':stamp(),'updatedAt':stamp(),'externalExecuted':False,'events':[],
               'note':'모의 검증 작업' if mode=='rehearsal' else '실제 연결·실행 승인 전 준비 작업'}
            db.execute(insert(jobs).values(id=r['id'],record=json.dumps(r,ensure_ascii=False)))
            return r
    def _write(self,db,r,event):
        r['revision']+=1;r['updatedAt']=stamp();r['events']=(r['events']+[{'event':event,'at':stamp()}])[-100:]
        db.execute(update(jobs).where(jobs.c.id==r['id']).values(record=json.dumps(r,ensure_ascii=False)));return r
    def action(self,key,revision,action):
        with self.store.engine.begin() as db:
            self.store.lock(db,901030)
            r=next((r for r in self._all(db) if r['id']==key),None)
            if r is None:raise HTTPException(404,'작업이 없습니다.')
            if type(revision) is not int or r['revision']!=revision:raise HTTPException(409,'작업이 변경됐습니다. 다시 불러오세요.')
            allowed={'pause':('queued',),'resume':('paused',),'cancel':('queued','paused','blocked','failed'),'retry':('failed',)}
            if not isinstance(action,str) or action not in allowed or r['status'] not in allowed[action]:raise HTTPException(409,'현재 상태에서 할 수 없는 작업입니다.')
            if action in ('resume','retry') and r['mode']!='rehearsal':raise HTTPException(409,'실제 실행은 아직 연결하지 않았습니다.')
            if action=='retry' and r['attempts']>=r['maxAttempts']:raise HTTPException(409,'재시도 한도에 도달했습니다.')
            r['status']={'pause':'paused','resume':'queued','cancel':'cancelled','retry':'queued'}[action]
            return self._write(db,r,action)
    def claim(self,key):
        with self.store.engine.begin() as db:
            self.store.lock(db,901030)
            r=next((r for r in self._all(db) if r['id']==key),None)
            if r is None:raise HTTPException(404,'작업이 없습니다.')
            if r['status']=='running' and r['leaseUntil']<time.time():
                r['status']='unknown';self._write(db,r,'lease_expired');return None
            if r['mode']!='rehearsal' or r['status']!='queued' or r['attempts']>=r['maxAttempts']:return None
            r.update(status='running',attempts=r['attempts']+1,lease=secrets.token_hex(24),leaseUntil=time.time()+60)
            self._write(db,r,'claimed');return r
    def run(self,key,handler):
        claim=self.claim(key)
        if not claim:return {'claimed':False}
        try:result=handler(claim['target']);status='succeeded'
        except Exception:result={'message':'모의 실행 실패 · 비밀값/외부 오류 원문은 표시하지 않습니다.'};status='failed'
        with self.store.engine.begin() as db:
            self.store.lock(db,901030)
            r=next(r for r in self._all(db) if r['id']==key)
            if r.get('lease')!=claim['lease'] or r['status']!='running' or r['leaseUntil']<time.time():
                raise HTTPException(409,'실행 소유권이 만료됐습니다. 자동 재실행하지 않습니다.')
            r.update(status=status,result=result,externalExecuted=False)
            r.pop('lease',None);r.pop('leaseUntil',None)
            return self._write(db,r,'rehearsal_'+status)
