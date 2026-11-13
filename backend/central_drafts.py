"""Append-only legacy draft history, with explicit preview and GET-only checking."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, select, insert
from central_store import metadata
from server import normalize_url, request_wp, validate_draft, VerificationError

draft_history = Table('wordpress_draft_history', metadata,
    Column('fingerprint', Text, primary_key=True), Column('record', Text, nullable=False),
    Column('imported_at', Text, nullable=False))


class DraftHistory:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        with store.engine.begin() as db:
            store.lock(db, 901001)
            draft_history.create(db, checkfirst=True)

    def preview(self, payload):
        if (set(payload) != {'format', 'version', 'records'} or payload['format'] != 'zero-seo-os-draft-history'
                or type(payload['version']) is not int or payload['version'] != 1
                or not isinstance(payload['records'], list) or not 1 <= len(payload['records']) <= 500):
            raise HTTPException(400, '초안 이력 파일 형식을 확인하세요.')
        result = []
        for record in payload['records']:
            if not isinstance(record, dict) or set(record) != {'url', 'postId', 'createdAt', 'source'}:
                raise HTTPException(400, '초안 이력 필드를 확인하세요. 인증정보는 가져올 수 없습니다.')
            if ((record['postId'] is not None and (type(record['postId']) is not int or not 0 < record['postId'] <= 2**53 - 1))
                    or not isinstance(record['source'], str) or not 1 <= len(record['source']) <= 100
                    or not isinstance(record['createdAt'], str) or not 1 <= len(record['createdAt']) <= 100):
                raise HTTPException(400, '글 ID·기록 시점·출처를 확인하세요. 불확실한 글 ID는 null로 보존하세요.')
            try:
                url = normalize_url(record['url'])
            except VerificationError:
                raise HTTPException(400, '초안 이력 사이트 주소를 확인하세요.') from None
            clean = {**record, 'url': url}
            fingerprint = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if not any(r['fingerprint'] == fingerprint for r in result):
                result.append({'fingerprint': fingerprint, 'record': clean})
        return result

    def save(self, payload):
        rows = self.preview(payload)
        added = 0
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            for row in rows:
                if db.execute(select(draft_history.c.fingerprint).where(draft_history.c.fingerprint == row['fingerprint'])).first():
                    continue
                db.execute(insert(draft_history).values(fingerprint=row['fingerprint'],
                    record=json.dumps(row['record'], ensure_ascii=False), imported_at=datetime.now(timezone.utc).isoformat()))
                added += 1
        return {'added': added, 'existing': len(rows) - added, 'wordpressChanged': False}

    def list(self):
        with self.store.engine.connect() as db:
            rows = db.execute(select(draft_history).order_by(draft_history.c.imported_at)).mappings().all()
        return [{'fingerprint': r['fingerprint'], **json.loads(r['record']), 'importedAt': r['imported_at']} for r in rows]

    def check(self, slot, fingerprint):
        if self.vault is None:
            raise HTTPException(503, '워드프레스 암호화 키 설정이 필요합니다.')
        with self.store.engine.connect() as db:
            raw = db.execute(select(draft_history.c.record).where(draft_history.c.fingerprint == fingerprint)).scalar_one_or_none()
        if raw is None:
            raise HTTPException(404, '초안 기록을 찾지 못했습니다.')
        record = json.loads(raw)
        if record['postId'] is None:
            raise HTTPException(409, '글 ID가 불확실한 기록입니다. 새 글을 생성하지 않습니다.')
        data, generation = self.vault.load(slot)
        if data['url'] != record['url']:
            raise HTTPException(409, '초안 기록과 사이트 주소가 다릅니다.')
        try:
            post = request_wp(data['url'], data['username'], data['password'], 'GET', f"/posts/{record['postId']}?context=edit")
            validate_draft(post, record['postId'])
        except VerificationError as error:
            raise HTTPException(502, str(error)) from None
        except Exception:
            raise HTTPException(502, '기존 초안 조회 결과 미확인 · 기존 기록은 유지됩니다.') from None
        _, current = self.vault.load(slot)
        if generation != current:
            raise HTTPException(409, '확인 중 인증정보가 변경됐습니다. 다시 확인하세요.')
        return {'postId': record['postId'], 'status': 'draft', 'draftConfirmed': True,
                'checkedAt': datetime.now(timezone.utc).isoformat(), 'wordpressChanged': False}
