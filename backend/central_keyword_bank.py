"""Stages 4-6: evidence-bound selection, persistent keyword assets and authoring handoff."""
import calendar
from datetime import datetime, timedelta
import hashlib
import json
import unicodedata
import uuid

from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, insert, select, update
from central_store import metadata, workspaces
from central_feeds import collections
from central_discovery import stamp
from server import normalize_url, VerificationError

keywords = Table('keyword_bank', metadata, Column('id', Text, primary_key=True), Column('record', Text, nullable=False))
events = Table('keyword_bank_events', metadata, Column('id', Text, primary_key=True), Column('keyword_id', Text, nullable=False), Column('at', Text, nullable=False), Column('record', Text, nullable=False))
preparations = Table('original_article_preparations', metadata, Column('id', Text, primary_key=True), Column('record', Text, nullable=False))


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def keyword_id(text):
    return hashlib.sha256(normalized(text).encode()).hexdigest()


def next_month(value):
    d = datetime.fromisoformat(value)
    year, month = d.year + (d.month == 12), d.month % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def fields(payload, expected):
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise HTTPException(400, '요청 필드를 확인하세요.')


class KeywordBank:
    def __init__(self, store, discovery):
        self.store, self.discovery = store, discovery
        with store.engine.begin() as db:
            store.lock(db, 901001)
            for table in (keywords, events, preparations): table.create(db, checkfirst=True)

    def read(self, db, key):
        raw = db.execute(select(keywords.c.record).where(keywords.c.id == key)).scalar_one_or_none()
        if raw is None: raise HTTPException(404, '키워드를 찾지 못했습니다.')
        return json.loads(raw)

    def get(self, key):
        with self.store.engine.connect() as db: return self.read(db, key)

    def version(self, row, revision):
        if type(revision) is not int or revision != row['revision']:
            raise HTTPException(409, '다른 요청에서 키워드가 변경됐습니다. 기록을 다시 불러오세요.')

    def write(self, db, row, event, detail=None):
        row['revision'] += 1
        row['updatedAt'] = stamp()
        db.execute(update(keywords).where(keywords.c.id == row['id']).values(record=json.dumps(row, ensure_ascii=False)))
        self.event(db, row['id'], event, detail or {})

    def event(self, db, key, kind, detail):
        db.execute(insert(events).values(id=str(uuid.uuid4()), keyword_id=key, at=stamp(), record=json.dumps({'event': kind, 'detail': detail}, ensure_ascii=False)))

    def list(self, offset=0):
        if type(offset) is not int or offset < 0: raise HTTPException(400, '목록 위치 오류입니다.')
        with self.store.engine.connect() as db:
            rows = db.execute(select(keywords.c.record).order_by(keywords.c.id).offset(offset).limit(101)).scalars().all()
        return {'keywords': [json.loads(r) for r in rows[:100]], 'nextOffset': offset + 100 if len(rows) > 100 else None}

    def history(self, key):
        self.get(key)
        with self.store.engine.connect() as db:
            rows = db.execute(select(events).where(events.c.keyword_id == key).order_by(events.c.at, events.c.id)).mappings().all()
        return [{'at': r['at'], **json.loads(r['record'])} for r in rows]

    def stage(self, payload):
        fields(payload, ('collectionId', 'selections'))
        if not isinstance(payload['collectionId'], str) or len(payload['collectionId']) > 100: raise HTTPException(400, '수집 기록 ID 오류입니다.')
        selections = payload['selections']
        if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
            raise HTTPException(400, '한 번에 후보 1~100개를 선택하세요.')
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            raw = db.execute(select(collections.c.record).where(collections.c.id == payload['collectionId'])).scalar_one_or_none()
            if raw is None: raise HTTPException(404, 'RSS 수집 기록을 찾지 못했습니다.')
            source = json.loads(raw)
            if source['status'] != 'collected': raise HTTPException(409, '수집 완료한 후보만 검토할 수 있습니다.')
            result = []
            for choice in selections:
                fields(choice, ('index', 'keyword'))
                i, text = choice['index'], choice['keyword']
                if (type(i) is not int or not 0 <= i < len(source['candidates']) or not isinstance(text, str)
                        or not 1 <= len(text.strip()) <= 200 or any(ord(c) < 32 for c in text)):
                    raise HTTPException(400, '후보 번호와 검색용 키워드(1~200자)를 확인하세요.')
                text = text.strip(); key = keyword_id(text)
                raw_row = db.execute(select(keywords.c.record).where(keywords.c.id == key)).scalar_one_or_none()
                provenance = {'collectionId': source['id'], 'candidateIndex': i, 'originalText': source['candidates'][i]['text'], 'blogUrl': source['blogUrl'], 'sources': source['candidates'][i]['sources'], 'searchSource': source.get('searchSource')}
                if raw_row:
                    row = json.loads(raw_row)
                    if provenance not in row['sources']:
                        row['sources'].append(provenance)
                        self.write(db, row, 'source_added', {'collectionId': source['id']})
                else:
                    row = {'id': key, 'keyword': text, 'revision': 1, 'status': 'pending', 'createdAt': stamp(), 'updatedAt': stamp(),
                           'sources': [provenance], 'latestRunId': None, 'verification': 'not_checked', 'checkedAt': None,
                           'nextCheckAt': None, 'retryAt': None, 'searchVolume': None, 'selectionMode': 'manual_no_volume_rule', 'reviewRequired': True, 'evidence': None}
                    db.execute(insert(keywords).values(id=key, record=json.dumps(row, ensure_ascii=False)))
                    self.event(db, key, 'candidate_staged', {'collectionId': source['id']})
                result.append(row)
            return {'keywords': result, 'note': '검토 대기이며 활성 DB 등록이 아닙니다.'}

    def attach(self, key, payload):
        fields(payload, ('revision', 'runId'))
        if not isinstance(payload['runId'], str) or len(payload['runId']) > 100: raise HTTPException(400, '검색 기록 ID 오류입니다.')
        run = self.discovery.get(payload['runId'])
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            row = self.read(db, key); self.version(row, payload['revision'])
            if normalized(run['keyword']) != normalized(row['keyword']): raise HTTPException(400, '다른 키워드의 검색 결과는 사용할 수 없습니다.')
            if row['evidence'] and run['createdAt'] < row['evidence']['createdAt']: raise HTTPException(409, '이전 검색 결과로 최신 확인을 덮어쓸 수 없습니다.')
            complete = all(run['engines'].get(e, {}).get('status') == 'retrieved' for e in ('naver', 'google'))
            row['latestRunId'] = run['id']
            row['evidence'] = run
            row['verification'] = 'both_retrieved' if complete else 'incomplete'
            present = any(e.get('targetPresence') == 'present' for e in run['engines'].values())
            row['reviewRequired'] = not (complete and present)
            row['retryAt'] = None if complete and present else (datetime.fromisoformat(stamp()) + timedelta(days=1)).isoformat()
            if complete:
                row['checkedAt'] = stamp()
                if row['status'] == 'active' and present: row['nextCheckAt'] = next_month(row['checkedAt'])
            self.write(db, row, 'search_checked' if complete else 'search_unverified', {'runId': run['id']})
            return row

    def check(self, key, payload):
        fields(payload, ('revision',))
        row = self.get(key); self.version(row, payload['revision'])
        run = self.discovery.create({'keyword': row['keyword']})
        return self.attach(key, {'revision': payload['revision'], 'runId': run['id']})

    def review(self, key, payload):
        fields(payload, ('revision', 'runId', 'decision', 'reason'))
        if payload['decision'] not in ('active', 'excluded') or not isinstance(payload['reason'], str) or not 1 <= len(payload['reason'].strip()) <= 500:
            raise HTTPException(400, '선택과 검토 이유를 입력하세요.')
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            row = self.read(db, key); self.version(row, payload['revision'])
            if row['verification'] != 'both_retrieved' or not row['latestRunId'] or payload['runId'] != row['latestRunId']:
                raise HTTPException(409, '네이버·구글 최신 검색을 모두 확인한 뒤 선별하세요.')
            if payload['decision'] == 'active' and not any(e.get('targetPresence') == 'present' for e in row['evidence']['engines'].values()):
                raise HTTPException(409, '대상 블로그 유형이 아직 확인되지 않았습니다. 유형 확인 후 검색 근거를 다시 연결하세요.')
            row['status'] = payload['decision']
            row['nextCheckAt'] = next_month(stamp()); row['retryAt'] = None; row['reviewRequired'] = False
            self.write(db, row, 'manual_' + payload['decision'], {'reason': payload['reason'].strip(), 'runId': row['latestRunId'], 'searchVolume': None})
            return row

    def handoff(self, key, payload):
        fields(payload, ('revision', 'slot'))
        if payload['slot'] not in ('A-1', 'A-2'): raise HTTPException(400, '대상 사이트를 확인하세요.')
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            row = self.read(db, key); self.version(row, payload['revision'])
            if row['status'] != 'active' or row['verification'] != 'both_retrieved' or row.get('reviewRequired', True): raise HTTPException(409, '활성·양쪽 확인 완료 키워드만 연결할 수 있습니다.')
            raw = db.execute(select(workspaces.c.data).order_by(workspaces.c.revision.desc()).limit(1)).scalar_one_or_none()
            if raw is None: raise HTTPException(409, '대상 워드프레스 사이트를 서버에 먼저 저장하세요.')
            site = json.loads(raw)['sites'][payload['slot']]
            try: url = normalize_url(site['url'])
            except VerificationError: raise HTTPException(409, '대상 사이트 HTTPS 주소를 서버에 저장하세요.') from None
            job_id = hashlib.sha256((key + '\n' + url).encode()).hexdigest()
            existing = db.execute(select(preparations.c.record).where(preparations.c.id == job_id)).scalar_one_or_none()
            if existing: return {'created': False, 'preparation': json.loads(existing)}
            job = {'id': job_id, 'keywordId': key, 'keyword': row['keyword'], 'slot': payload['slot'], 'siteUrl': url, 'siteName': site['name'],
                   'createdAt': stamp(), 'status': 'writing_preparation', 'evidenceRunId': row['latestRunId'], 'articleGenerated': False}
            db.execute(insert(preparations).values(id=job_id, record=json.dumps(job, ensure_ascii=False)))
            self.event(db, key, 'original_article_handoff', {'preparationId': job_id, 'slot': payload['slot'], 'siteUrl': url})
            return {'created': True, 'preparation': job}

    def queue(self):
        with self.store.engine.connect() as db:
            rows = db.execute(select(preparations.c.record).order_by(preparations.c.id)).scalars().all()
            result = []
            current = db.execute(select(workspaces.c.data).order_by(workspaces.c.revision.desc()).limit(1)).scalar_one_or_none()
            sites = json.loads(current)['sites'] if current else {}
            for raw in rows:
                job = json.loads(raw); row = self.read(db, job['keywordId'])
                url = sites.get(job['slot'], {}).get('url', '').rstrip('/')
                job['eligible'] = row['status'] == 'active' and row['verification'] == 'both_retrieved' and not row.get('reviewRequired', True) and url == job['siteUrl']
                result.append(job)
        return result

    def due(self, limit=5):
        # Deliberately bounded; scheduled runner and owner screen use the same operation.
        if type(limit) is not int or not 1 <= limit <= 5: raise HTTPException(400, '검사 묶음은 1~5개입니다.')
        now = stamp()
        with self.store.engine.connect() as db: rows = [json.loads(r) for r in db.execute(select(keywords.c.record)).scalars()]
        due = [r for r in rows if r['status'] == 'active' and r['nextCheckAt'] and ((r['retryAt'] and r['retryAt'] <= now) or (not r['retryAt'] and r['nextCheckAt'] <= now))]
        result = []
        for row in sorted(due, key=lambda r: r['retryAt'] or r['nextCheckAt'])[:limit]:
            try: result.append({'id': row['id'], 'record': self.check(row['id'], {'revision': row['revision']})})
            except HTTPException as e: result.append({'id': row['id'], 'status': 'unverified', 'httpStatus': e.status_code})
        return result

    def export(self):
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            rows = [json.loads(r) for r in db.execute(select(keywords.c.record)).scalars()]
            history = [{'id': r['id'], 'keywordId': r['keyword_id'], 'at': r['at'], **json.loads(r['record'])} for r in db.execute(select(events)).mappings()]
            jobs = [json.loads(r) for r in db.execute(select(preparations.c.record)).scalars()]
        return {'format': 'zero-keyword-bank-export', 'version': 1, 'exportedAt': stamp(), 'keywords': rows, 'events': history, 'preparations': jobs}
