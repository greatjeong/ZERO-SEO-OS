"""Private central foundation: login, versioned workspace and backup import.
No WordPress credentials, no WordPress requests, no automatic local data migration.
Run uvicorn central:create_app --factory --app-dir backend after setting config.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from central_auth import valid_hash, verify_password
from storage import validate

VERSION = '0.3.0-foundation'
COOKIE = '__Host-zero_session'
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY = 5 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    origin: str
    data_dir: Path
    owner_hash: str = field(repr=False)
    static_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / 'frontend/dist')

    def __post_init__(self):
        p = urlsplit(self.origin)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.path or p.query or p.fragment or p.port not in (None, 443)):
            raise ValueError('ZERO_CENTRAL_ORIGIN must be a bare HTTPS origin, without trailing slash.')
        if not valid_hash(self.owner_hash):
            raise ValueError('ZERO_OWNER_PASSWORD_HASH must be configured; no default password exists.')
        if self.data_dir.resolve() == Path(__file__).resolve().parent / '.state':
            raise ValueError('Use a dedicated central data directory; preserve legacy .state.')

    @classmethod
    def from_env(cls):
        directory = os.environ.get('ZERO_CENTRAL_DATA_DIR')
        if not directory:
            raise ValueError('ZERO_CENTRAL_DATA_DIR must point to persistent private storage.')
        return cls(os.environ.get('ZERO_CENTRAL_ORIGIN', ''), Path(directory),
                   os.environ.get('ZERO_OWNER_PASSWORD_HASH', ''))


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'central.sqlite3'
        with closing(self.connect()) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise ValueError('Unknown central schema version; database was not modified.')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
                    expires REAL NOT NULL, auth_revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (client TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS login_time ON login_attempts(at);
                CREATE TABLE IF NOT EXISTS workspaces (
                    revision INTEGER PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')
            db.commit()
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def current(self):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM workspaces ORDER BY revision DESC LIMIT 1').fetchone()
            return {'revision': row['revision'], 'data': json.loads(row['data'])} if row else {'revision': 0, 'data': None}

    def save(self, base_revision, data):
        if type(base_revision) is not int or base_revision < 0:
            raise HTTPException(400, '저장 기준 버전이 올바르지 않습니다.')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT COALESCE(MAX(revision),0) FROM workspaces').fetchone()[0]
            if current != base_revision:
                raise HTTPException(409, '다른 창에서 먼저 저장했습니다. 현재 변경을 백업한 뒤 서버 데이터를 다시 불러오세요.')
            revision = current + 1
            db.execute('INSERT INTO workspaces VALUES (?,?,?)',
                       (revision, datetime.now(timezone.utc).isoformat(), json.dumps(data, ensure_ascii=False)))
            db.commit()
        return {'revision': revision, 'data': data}

    def login_allowed(self, client):
        now = time.time()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_attempts WHERE at < ?', (now - 60,))
            count = db.execute('SELECT COUNT(*) FROM login_attempts WHERE client=?', (client,)).fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM login_attempts').fetchone()[0]
            if count >= 5 or total >= 20:
                raise HTTPException(429, '로그인 시도가 많습니다. 잠시 후 다시 시도하세요.')
            db.execute('INSERT INTO login_attempts VALUES (?,?)', (client, now))
            db.commit()


async def read_json(request):
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        raise HTTPException(415, 'JSON 요청이 필요합니다.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, '파일은 5MB 이하여야 합니다.')
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, 'JSON 형식 오류입니다.') from None
    if not isinstance(data, dict):
        raise HTTPException(400, '객체 형식 요청이 필요합니다.')
    return data


def checked_backup(data, current=None):
    if not isinstance(data, dict) or type(data.get('version')) is not int:
        raise HTTPException(400, '백업 버전 형식이 올바르지 않습니다.')
    # v1 imports retain the existing site's public metadata. Never silently replace it.
    if isinstance(data, dict) and data.get('version') == 1:
        if set(data) - {'format', 'version', 'exportedAt', 'keywordsBySite', 'jobs'}:
            raise HTTPException(400, '허용되지 않은 백업 필드입니다.')
        sites = current['sites'] if current else {slot: {'name': '', 'url': ''} for slot in ('A-1', 'A-2')}
        data = {**data, 'version': 2, 'sites': sites,
                'exportedAt': data.get('exportedAt', datetime.now(timezone.utc).isoformat())}
    try:
        validate(data)
    except Exception:
        raise HTTPException(400, '백업 형식·사이트·작업을 확인하세요. 인증정보는 가져올 수 없습니다.') from None
    return data


def create_app(settings=None):
    cfg = settings or Settings.from_env()
    store = Store(cfg.data_dir)
    auth_revision = hashlib.sha256(cfg.owner_hash.encode()).hexdigest()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    login_gate = threading.BoundedSemaphore(2)
    app.state.login_gate = login_gate

    def verify_limited(password):
        if not login_gate.acquire(blocking=False):
            raise HTTPException(429, '로그인 확인이 진행 중입니다. 잠시 후 다시 시도하세요.')
        try:
            return verify_password(password, cfg.owner_hash)
        finally:
            login_gate.release()

    @app.exception_handler(HTTPException)
    async def safe_http(_request, error):
        return JSONResponse({'message': str(error.detail)}, status_code=error.status_code)

    @app.middleware('http')
    async def response_security(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def same_origin(request):
        if request.headers.get('origin') != cfg.origin:
            raise HTTPException(403, '허용되지 않은 요청 출처입니다.')

    def session(request, write=False):
        token = request.cookies.get(COOKIE, '')
        if len(token) > 128:
            raise HTTPException(401, '로그인이 필요합니다.')
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with closing(store.connect()) as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>? AND auth_revision=?',
                             (hashed, time.time(), auth_revision)).fetchone()
        if not row:
            raise HTTPException(401, '로그인이 필요합니다.')
        if write:
            same_origin(request)
            if not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), row['csrf'].encode()):
                raise HTTPException(403, '보안 확인이 만료됐습니다. 다시 로그인하세요.')
        return row

    @app.get('/api/health')
    def health():
        return {'version': VERSION, 'mode': 'private-owner', 'wordpressEnabled': False}

    @app.post('/api/login')
    async def login(request: Request):
        same_origin(request)
        data = await read_json(request)
        if set(data) != {'password'} or not isinstance(data['password'], str) or len(data['password']) > 256:
            raise HTTPException(400, '로그인 입력 형식 오류입니다.')
        client = request.client.host if request.client else 'unknown'
        store.login_allowed(client)
        if not await run_in_threadpool(verify_limited, data['password']):
            raise HTTPException(401, '로그인 정보를 확인하세요.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with closing(store.connect()) as db:
            db.execute('DELETE FROM sessions WHERE expires <= ? OR auth_revision != ?', (time.time(), auth_revision))
            # Rotate the current browser's session; other browsers may stay logged in.
            old = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
            db.execute('DELETE FROM sessions WHERE token_hash=?', (old,))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + SESSION_SECONDS, auth_revision))
            db.execute('DELETE FROM login_attempts WHERE client=?', (client,))
            db.commit()
        response = JSONResponse({'authenticated': True, 'csrf': csrf})
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True,
                            samesite='strict', path='/')
        return response

    @app.get('/api/session')
    def whoami(request: Request):
        row = session(request)
        return {'authenticated': True, 'csrf': row['csrf']}

    @app.post('/api/logout')
    def logout(request: Request):
        row = session(request, write=True)
        with closing(store.connect()) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (row['token_hash'],))
            db.commit()
        response = JSONResponse({'loggedOut': True})
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='strict', path='/')
        return response

    @app.get('/api/workspace')
    def workspace(request: Request):
        session(request)
        return store.current()

    @app.put('/api/workspace')
    async def save_workspace(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        if set(payload) != {'baseRevision', 'data'}:
            raise HTTPException(400, '저장 요청 필드 오류입니다.')
        data = checked_backup(payload['data'])
        return store.save(payload['baseRevision'], data)

    @app.post('/api/import/preview')
    async def import_preview(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        current = store.current()
        data = checked_backup(payload, current['data'])
        return {'baseRevision': current['revision'], 'data': data,
                'counts': {slot: len(data['keywordsBySite'][slot]) for slot in ('A-1', 'A-2')},
                'jobs': len(data['jobs'])}

    @app.get('/api/snapshots')
    def snapshots(request: Request):
        session(request)
        with closing(store.connect()) as db:
            rows = db.execute('SELECT revision, created_at FROM workspaces ORDER BY revision DESC LIMIT 100').fetchall()
        return {'snapshots': [dict(row) for row in rows]}

    @app.get('/api/snapshots/{revision}')
    def snapshot(revision: int, request: Request):
        session(request)
        with closing(store.connect()) as db:
            row = db.execute('SELECT revision, data FROM workspaces WHERE revision=?', (revision,)).fetchone()
        if row is None:
            raise HTTPException(404, '저장본을 찾지 못했습니다.')
        return {'revision': row['revision'], 'data': json.loads(row['data'])}

    # Only built public assets are served. Never mount the repository or data directory.
    if (cfg.static_dir / 'central.html').is_file():
        @app.get('/')
        def home():
            return RedirectResponse('/central.html')

        @app.get('/central.html')
        def central_page():
            return FileResponse(cfg.static_dir / 'central.html', headers={'Cache-Control': 'no-store'})

        app.mount('/assets', StaticFiles(directory=cfg.static_dir / 'assets'), name='assets')
    return app
