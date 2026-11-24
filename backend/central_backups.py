"""Portable application-data archive. Secrets/sessions excluded; restore adds missing rows only."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select,insert
from sqlalchemy.exc import IntegrityError
from central_store import metadata
from central_discovery import stamp

NAMES=('workspaces','keyword_search_runs','keyword_feed_collections','keyword_bank','keyword_bank_events',
       'original_article_preparations','original_article_documents','original_article_versions','hub_records','network_links','operation_settings')


def checksum(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class Backups:
    def __init__(self,store):self.store=store
    def tables(self):return {name:metadata.tables[name] for name in NAMES if name in metadata.tables}
    def export(self):
        tables={}
        with self.store.engine.connect() as db:
            # Repeatable snapshot for all data tables; never expose sessions, encrypted keys or intents.
            if self.store.kind=='postgresql':db.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            else:db.exec_driver_sql('BEGIN')
            for name,table in self.tables().items():tables[name]=[dict(r) for r in db.execute(select(table)).mappings()]
        return {'format':'zero-application-archive','version':1,'exportedAt':stamp(),'tables':tables,
                'checksum':checksum(tables),'excluded':['sessions','credentials','login_attempts','operation_jobs','wordpress_draft_intents','wordpress_draft_history','original_draft_transfers'],
                'scope':'작업 데이터 보관본 · DB 전체/인증키/WP 중복방지 기록 백업은 별도 필요'}
    def validate(self,p):
        if not isinstance(p,dict) or p.get('format')!='zero-application-archive' or type(p.get('version')) is not int or p['version']!=1 or not isinstance(p.get('tables'),dict):
            raise HTTPException(400,'작업 데이터 보관본 형식을 확인하세요.')
        tables=p['tables']
        if set(tables)!=set(self.tables()) or checksum(tables)!=p.get('checksum'):
            raise HTTPException(400,'백업 범위·체크섬이 다릅니다. 원본 파일을 확인하세요.')
        count=0
        for name,rows in tables.items():
            table=self.tables()[name];seen=set()
            if not isinstance(rows,list):raise HTTPException(400,'테이블 목록 형식을 확인하세요.')
            for row in rows:
                if not isinstance(row,dict) or set(row)!=set(table.c.keys()):raise HTTPException(400,'백업 열 형식이 다릅니다.')
                key=next(iter(table.primary_key.columns)).name;identity=row[key]
                if not isinstance(identity,(str,int)) or isinstance(identity,bool) or (isinstance(identity,str) and len(identity)>1000) or identity in seen:raise HTTPException(400,'백업 식별자 중복·형식을 확인하세요.')
                seen.add(identity);count+=1
                for col,value in row.items():
                    if col=='revision':
                        if type(value) is not int or value<1:raise HTTPException(400,'작업 공간 버전을 확인하세요.')
                    elif not isinstance(value,str) or len(value)>2000000:raise HTTPException(400,'백업 데이터 길이·형식을 확인하세요.')
                try:
                    record=json.loads(row.get('record',row.get('data','{}')))
                    if not isinstance(record,dict):raise ValueError()
                    if 'id' in record and record['id']!=identity:raise ValueError()
                    if name=='hub_records':
                        from central_hub import clean
                        if type(record.get('revision')) is not int or record['revision']<0:raise ValueError()
                        clean(identity,record['data'])
                    if name=='workspaces':
                        from storage import validate
                        validate(record)
                    if name=='operation_settings':
                        from central_workbench import DEFAULT
                        if identity!='providers' or set(record.get('data',{}))!=set(DEFAULT) or type(record.get('revision')) is not int or record['revision']<0:raise ValueError()
                    if name=='original_article_versions':
                        d=record['document']
                        if not isinstance(d,dict) or type(d['revision']) is not int or d['revision']<1 or d['id']!=row['document_id'] or identity!=d['id']+':'+str(d['revision']):raise ValueError()
                        if not isinstance(record.get('event'),str):raise ValueError()
                    if name in ('keyword_bank','original_article_preparations','network_links'):
                        if type(record.get('revision',1)) is not int or record.get('revision',1)<1:raise ValueError()
                    if name=='original_article_documents':
                        from central_adapters import text
                        draft=record['draft'];text(draft['title'],200,True);text(draft['body'],50000,True)
                        if type(record['revision']) is not int or record['revision']<1:raise ValueError()
                        if not isinstance(record.get('outline'),list) or len(record['outline'])>30:raise ValueError()
                        for line in record['outline']:text(line,200,True)
                except (ValueError,TypeError,KeyError):raise HTTPException(400,'백업 기록 내용을 확인하세요.') from None
        if count>10000:raise HTTPException(400,'한 번에 10000행 이하로 복구하세요.')
        return tables
    def _plan(self,db,tables):
        details=[];state={}
        for name,rows in tables.items():
            table=self.tables()[name];key=next(iter(table.primary_key.columns)).name
            current={r[key]:dict(r) for r in db.execute(select(table)).mappings()}
            details.append({'table':name,'add':sum(r[key] not in current for r in rows),
                            'same':sum(r[key] in current and current[r[key]]==r for r in rows),
                            'conflictsKept':sum(r[key] in current and current[r[key]]!=r for r in rows)})
            state[name]=sorted(current.values(),key=lambda r:str(r[key]))
        return {'details':details,'basis':checksum(state),'checksum':checksum(tables),'mode':'add_missing_only',
                'note':'기존 행·현재 편집본은 덮어쓰지 않습니다. 충돌은 그대로 보존하며 문서 이전 버전 복원은 원본 글 화면에서 진행하세요.'}
    def preview(self,p):
        tables=self.validate(p)
        with self.store.engine.connect() as db:return self._plan(db,tables)
    def restore(self,p):
        if not isinstance(p,dict) or set(p)!={'archive','basis'}:raise HTTPException(400,'복구 미리보기를 먼저 확인하세요.')
        tables=self.validate(p['archive'])
        try:
            with self.store.engine.begin() as db:
                self.store.lock(db,901002)
                plan=self._plan(db,tables)
                if p['basis']!=plan['basis']:raise HTTPException(409,'미리보기 후 데이터가 바뀌었습니다. 미리보기를 다시 확인하세요.')
                # Dependency order; imports are strictly additive, never restoring tokens or active jobs.
                for name,rows in tables.items():
                    table=self.tables()[name];key=next(iter(table.primary_key.columns)).name
                    keys=set(db.execute(select(table.c[key])).scalars())
                    for row in rows:
                        if row[key] not in keys:db.execute(insert(table).values(**row))
            return {**plan,'added':sum(d['add'] for d in plan['details']),'restoredAt':stamp(),'externalExecuted':False}
        except IntegrityError:raise HTTPException(409,'다른 작업과 충돌했습니다. 아무것도 덮어쓰지 않았습니다. 다시 미리보기 하세요.') from None
