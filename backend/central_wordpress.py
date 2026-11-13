"""Owner-only encrypted WordPress credentials; read-only verification only."""
import json
import re
import secrets
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, select, insert, update
from central_store import metadata, workspaces
from server import normalize_url, request_identity, VerificationError

credentials = Table('wordpress_credentials', metadata,
                    Column('slot', Text, primary_key=True),
                    Column('token', Text, nullable=False),
                    Column('generation', Text, nullable=False))


class WordPressVault:
    def __init__(self, store, key):
        self.store = store
        try:
            self.cipher = Fernet(key)
        except Exception:
            raise ValueError('Invalid ZERO_WP_ENCRYPTION_KEY; value is never shown.') from None
        with store.engine.begin() as db:
            store.lock(db, 901001)
            credentials.create(db, checkfirst=True)

    def site_url(self, db, slot):
        if slot not in ('A-1', 'A-2'):
            raise HTTPException(404, '사이트를 찾지 못했습니다.')
        raw = db.execute(select(workspaces.c.data).order_by(workspaces.c.revision.desc()).limit(1)).scalar_one_or_none()
        url = json.loads(raw)['sites'][slot]['url'] if raw else ''
        try:
            return normalize_url(url)
        except VerificationError:
            raise HTTPException(400, '사이트 주소를 먼저 서버에 저장하세요.') from None

    def save(self, slot, payload):
        if set(payload) != {'username', 'applicationPassword'}:
            raise HTTPException(400, '인증정보 입력 필드를 확인하세요.')
        username, password = payload['username'], payload['applicationPassword']
        if (not isinstance(username, str) or not username or len(username) > 254
                or ':' in username or any(ord(c) < 33 for c in username)
                or not isinstance(password, str) or len(password) > 128):
            raise HTTPException(400, '사용자명과 앱 비밀번호 형식을 확인하세요.')
        password = password.replace(' ', '')
        if not re.fullmatch(r'[A-Za-z0-9]{24}', password):
            raise HTTPException(400, '24자리 워드프레스 앱 비밀번호가 필요합니다.')
        with self.store.engine.begin() as db:
            self.store.lock(db, 901002)
            url = self.site_url(db, slot)
            token = self.cipher.encrypt(json.dumps({'slot': slot, 'url': url, 'username': username, 'password': password}).encode()).decode()
            values = {'token': token, 'generation': secrets.token_hex(16)}
            exists = db.execute(select(credentials.c.slot).where(credentials.c.slot == slot)).first()
            if exists:
                db.execute(update(credentials).where(credentials.c.slot == slot).values(**values))
            else:
                db.execute(insert(credentials).values(slot=slot, **values))
        return {'configured': True, 'verified': False}

    def load(self, slot):
        with self.store.engine.connect() as db:
            url = self.site_url(db, slot)
            row = db.execute(select(credentials).where(credentials.c.slot == slot)).mappings().first()
        if not row:
            raise HTTPException(409, '앱 비밀번호를 먼저 등록하세요.')
        try:
            data = json.loads(self.cipher.decrypt(row['token'].encode()))
        except (InvalidToken, ValueError, UnicodeError):
            raise HTTPException(503, '인증정보 복호화 실패 · 서버 암호화 키를 확인하세요. 기존 기록은 유지됩니다.') from None
        if data['slot'] != slot or data['url'] != url:
            raise HTTPException(409, '사이트 주소가 변경됐습니다. 인증정보를 다시 등록하세요.')
        return data, row['generation']

    def verify(self, slot):
        data, generation = self.load(slot)
        try:
            identity = request_identity(data['url'], data['username'], data['password'])
        except VerificationError as error:
            raise HTTPException(502, str(error)) from None
        except Exception:
            raise HTTPException(502, '워드프레스 연결 결과 미확인 · 네트워크와 인증을 확인하세요.') from None
        _, current = self.load(slot)
        if generation != current:
            raise HTTPException(409, '확인 중 인증정보가 변경됐습니다. 다시 확인하세요.')
        caps = identity.get('capabilities')
        def cap(name):
            value = caps.get(name, False) if isinstance(caps, dict) else None
            return value if type(value) is bool else None
        return {'verified': True, 'url': data['url'], 'checkedAt': datetime.now(timezone.utc).isoformat(),
                'permissions': {'editPosts': cap('edit_posts'), 'publishPosts': cap('publish_posts')}}
