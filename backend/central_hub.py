"""Owner-only guide progress and planning records. No external execution."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, insert, select, update
from central_store import metadata

records = Table('hub_records', metadata, Column('kind', Text, primary_key=True), Column('record', Text, nullable=False))
SCHEMAS = {'pbn': ('sites','original','language','interval','notes'),
           'backlinks': ('target','candidates','criteria','review','notes'),
           'index': ('site','google','naver','daum','bing','note')}

def clean(kind, data):
    if not isinstance(data, dict): raise HTTPException(400, '기록 형식을 확인하세요.')
    if kind == 'progress':
        if len(data)>48: raise HTTPException(400, '가이드는 48개입니다.')
        for key, row in data.items():
            if not re.fullmatch(r'S(0[1-9]|1[0-2])-C0[1-4]',key): raise HTTPException(400,'알 수 없는 가이드입니다.')
            if (not isinstance(row,dict) or set(row)!={'status','note','verify'} or not isinstance(row['status'],str) or row['status'] not in ('todo','doing','done','blocked')
                or not isinstance(row['note'],str) or len(row['note'])>5000 or not isinstance(row['verify'],list)
                or len(row['verify'])!=2 or any(type(v) is not bool for v in row['verify'])):
                raise HTTPException(400,'가이드 기록 형식을 확인하세요.')
            if row['status']=='done' and not all(row['verify']): raise HTTPException(400,'완료 확인 두 항목을 먼저 체크하세요.')
    elif kind in SCHEMAS:
        if set(data)!=set(SCHEMAS[kind]) or any(not isinstance(v,str) or len(v)>10000 for v in data.values()):
            raise HTTPException(400,'설정 형식을 확인하세요.')
        url_keys={'pbn':['original'],'backlinks':['target'],'index':['site']}[kind]
        urls=[data[k].strip() for k in url_keys if data[k].strip()]
        list_key={'pbn':'sites','backlinks':'candidates'}.get(kind)
        if list_key: urls += [line.split()[0] for line in data[list_key].splitlines() if line.strip()]
        for value in urls:
            try:
                u=urlsplit(value)
                if u.scheme not in ('https','http') or not u.hostname or u.username or u.password: raise ValueError()
                u.port
            except ValueError: raise HTTPException(400,'주소는 로그인 정보 없는 http(s) URL로 입력하세요.') from None
    else: raise HTTPException(404,'기록 영역을 찾지 못했습니다.')
    return data

class Hub:
    def __init__(self, store):
        self.store=store
        with store.engine.begin() as db:
            store.lock(db,901001); records.create(db,checkfirst=True)
    def get(self,kind):
        if kind not in (*SCHEMAS,'progress'): raise HTTPException(404,'기록 영역을 찾지 못했습니다.')
        with self.store.engine.connect() as db:
            raw=db.execute(select(records.c.record).where(records.c.kind==kind)).scalar_one_or_none()
        return json.loads(raw) if raw else {'revision':0,'data':{} if kind=='progress' else {k:'' for k in SCHEMAS[kind]},'updatedAt':None}
    def save(self,kind,payload):
        if not isinstance(payload,dict) or set(payload)!={'revision','data'} or type(payload['revision']) is not int or payload['revision']<0:
            raise HTTPException(400,'저장 버전을 확인하세요.')
        data=clean(kind,payload['data'])
        with self.store.engine.begin() as db:
            self.store.lock(db,901020)
            raw=db.execute(select(records.c.record).where(records.c.kind==kind)).scalar_one_or_none()
            revision=json.loads(raw)['revision'] if raw else 0
            if payload['revision']!=revision: raise HTTPException(409,'다른 창에서 변경했습니다. 현재 입력을 내보내고 다시 불러오세요.')
            row={'revision':revision+1,'data':data,'updatedAt':datetime.now(timezone.utc).isoformat()}
            query=update(records).where(records.c.kind==kind) if raw else insert(records).values(kind=kind)
            db.execute(query.values(record=json.dumps(row,ensure_ascii=False)))
        return row
