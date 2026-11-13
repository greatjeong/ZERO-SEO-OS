"""One test draft per canonical site. Durable intent before any WordPress write."""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, BigInteger, select, insert, update
from central_store import metadata
from central_wordpress import credentials
from central_drafts import draft_history
from server import request_identity, request_wp, validate_draft, VerificationError, TEST_TITLE, TEST_CONTENT

intents = Table('wordpress_draft_intents', metadata,
    Column('url', Text, primary_key=True), Column('post_id', BigInteger),
    Column('created_at', Text, nullable=False), Column('checked_at', Text))


class DraftSaver:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        with store.engine.begin() as db:
            store.lock(db, 901001)
            intents.create(db, checkfirst=True)

    def require_vault(self):
        if self.vault is None:
            raise HTTPException(503, '워드프레스 암호화 키 설정이 필요합니다.')

    def unchanged(self, slot, generation):
        _, current = self.vault.load(slot)
        if generation != current:
            raise HTTPException(409, '확인 중 사이트 또는 인증정보가 변경됐습니다. 기존 저장 기록은 유지됩니다.')

    def state(self, slot):
        self.require_vault()
        data, _ = self.vault.load(slot)
        with self.store.engine.connect() as db:
            row = db.execute(select(intents).where(intents.c.url == data['url'])).mappings().first()
        return {'url': data['url'], 'intent': ({'postId': row['post_id'], 'createdAt': row['created_at'],
                'lastConfirmedAt': row['checked_at']} if row else None)}

    def create(self, slot, payload):
        self.require_vault()
        if (set(payload) != {'url', 'confirmDraft', 'legacyHistoryReviewed'}
                or payload['confirmDraft'] is not True or payload['legacyHistoryReviewed'] is not True):
            raise HTTPException(400, '기존 PC 초안 이력 확인과 새 테스트 초안 저장 승인이 필요합니다.')
        data, generation = self.vault.load(slot)
        if payload['url'] != data['url']:
            raise HTTPException(409, '대상 사이트가 변경됐습니다. 다시 확인하세요.')
        # Only read capability before reserving. Never send a POST without explicit edit permission.
        try:
            identity = request_identity(data['url'], data['username'], data['password'])
        except VerificationError as error:
            raise HTTPException(502, str(error)) from None
        except Exception:
            raise HTTPException(502, '사용자 권한 조회 실패 · 초안을 생성하지 않았습니다.') from None
        if not isinstance(identity.get('capabilities'), dict) or identity['capabilities'].get('edit_posts') is not True:
            raise HTTPException(403, '글 작성 권한을 확인하지 못해 초안을 생성하지 않았습니다.')
        with self.store.engine.begin() as db:
            # Same lock as workspace/credential updates and history import. Across slots/processes.
            self.store.lock(db, 901002)
            url = self.vault.site_url(db, slot)
            current = db.execute(select(credentials.c.generation).where(credentials.c.slot == slot)).scalar_one_or_none()
            if url != data['url'] or current != generation:
                raise HTTPException(409, '대상 사이트 또는 인증정보가 변경돼 생성하지 않았습니다.')
            if db.execute(select(intents.c.url).where(intents.c.url == url)).first():
                raise HTTPException(409, '이 사이트에 저장 시도 기록이 있습니다. 새 글을 만들지 말고 저장 결과 재확인을 이용하세요.')
            records = db.execute(select(draft_history.c.record)).scalars()
            if any(json.loads(record)['url'] == url for record in records):
                raise HTTPException(409, '기존 초안 이력이 있습니다. 이력의 기존 글 상태 확인을 이용하세요. 추가 생성하지 않습니다.')
            db.execute(insert(intents).values(url=url, post_id=None,
                created_at=datetime.now(timezone.utc).isoformat(), checked_at=None))
        # Intent COMMITTED before write. No automatic retry and no deletion, even on timeout/crash.
        try:
            post = request_wp(data['url'], data['username'], data['password'], 'POST', '/posts', {
                'title': TEST_TITLE, 'content': TEST_CONTENT, 'status': 'draft',
                'comment_status': 'closed', 'ping_status': 'closed'})
            post_id = post.get('id') if isinstance(post, dict) else None
            if type(post_id) is not int or not 0 < post_id <= 2**53 - 1:
                raise VerificationError('응답 글 ID 미확인')
            # Preserve a returned ID even if status/readback subsequently fails.
            with self.store.engine.begin() as db:
                db.execute(update(intents).where(intents.c.url == data['url']).values(post_id=post_id))
            validate_draft(post, post_id)
        except Exception:
            raise HTTPException(502, '초안 저장 결과 미확인 · 중복 생성을 차단했습니다. 저장 결과 재확인 또는 워드프레스 글 목록을 확인하세요.') from None
        return self.check(slot, expected=(data['url'], generation))

    def check(self, slot, expected=None):
        self.require_vault()
        data, generation = self.vault.load(slot)
        if expected is not None and expected != (data['url'], generation):
            raise HTTPException(409, '대상 또는 인증정보 변경 · 기존 저장 기록을 보존했습니다. 원래 사이트에서 재확인하세요.')
        with self.store.engine.connect() as db:
            row = db.execute(select(intents).where(intents.c.url == data['url'])).mappings().first()
        if row is None:
            raise HTTPException(404, '이 사이트의 중앙 저장 시도 기록이 없습니다. 기존 이력도 확인하세요.')
        if row['post_id'] is None:
            raise HTTPException(409, '글 ID가 불확실한 저장 시도입니다. 재생성을 차단했습니다. 워드프레스 글 목록을 먼저 확인하세요.')
        try:
            post = request_wp(data['url'], data['username'], data['password'], 'GET', f"/posts/{row['post_id']}?context=edit")
            validate_draft(post, row['post_id'])
        except VerificationError as error:
            raise HTTPException(502, str(error)) from None
        except Exception:
            raise HTTPException(502, '초안 재조회 결과 미확인 · 저장 기록을 보존하고 재생성을 차단했습니다.') from None
        self.unchanged(slot, generation)
        checked = datetime.now(timezone.utc).isoformat()
        with self.store.engine.begin() as db:
            db.execute(update(intents).where(intents.c.url == data['url']).values(checked_at=checked))
        return {'url': data['url'], 'postId': row['post_id'], 'status': 'draft',
                'draftConfirmed': True, 'checkedAt': checked}
