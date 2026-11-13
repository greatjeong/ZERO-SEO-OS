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
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from central_auth import hash_password, valid_hash, verify_password
from central_store import Store, postgres_url
from storage import validate

VERSION = '0.3.1-postgres'
COOKIE = '__Host-zero_session'
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY = 5 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    origin: str
    data_dir: Path | None
    owner_hash: str = field(repr=False)
    static_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / 'frontend/dist')

    database_url: str | None = field(default=None, repr=False)

    def __post_init__(self):
        p = urlsplit(self.origin)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.path or p.query or p.fragment or p.port not in (None, 443)):
            raise ValueError('ZERO_CENTRAL_ORIGIN must be a bare HTTPS origin, without trailing slash.')
        if not valid_hash(self.owner_hash):
            raise ValueError('ZERO_OWNER_PASSWORD_HASH must be configured; no default password exists.')
        if self.database_url:
            postgres_url(self.database_url)
        elif self.data_dir is None:
            raise ValueError('Configure DATABASE_URL for PostgreSQL or a private SQLite directory for development.')
        if self.data_dir is not None and self.data_dir.resolve() == Path(__file__).resolve().parent / '.state':
            raise ValueError('Use a dedicated central data directory; preserve legacy .state.')

    @classmethod
    def from_env(cls):
        directory = os.environ.get('ZERO_CENTRAL_DATA_DIR')
        database = os.environ.get('DATABASE_URL')
        if not database and not directory:
            raise ValueError('Configure DATABASE_URL for production; no ephemeral fallback is used.')
        encoded = os.environ.get('ZERO_OWNER_PASSWORD_HASH')
        if not encoded:
            password = os.environ.get('ZERO_OWNER_PASSWORD', '')
            encoded = hash_password(password)
        origin = os.environ.get('ZERO_CENTRAL_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL', '')
        return cls(origin.rstrip('/'), Path(directory) if directory else None, encoded, database_url=database)


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
    store = Store(cfg.data_dir, cfg.database_url)
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
        row = store.find_session(hashed, auth_revision)
        if not row:
            raise HTTPException(401, '로그인이 필요합니다.')
        if write:
            same_origin(request)
            if not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), row['csrf'].encode()):
                raise HTTPException(403, '보안 확인이 만료됐습니다. 다시 로그인하세요.')
        return row

    @app.get('/api/health')
    def health():
        return {'version': VERSION, 'mode': 'private-owner', 'database': store.kind, 'wordpressEnabled': False}

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
        old = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
        store.issue_session(hashlib.sha256(token.encode()).hexdigest(), csrf,
                            time.time() + SESSION_SECONDS, auth_revision, old, client)
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
        store.revoke_session(row['token_hash'])
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
        return {'snapshots': store.snapshots()}

    @app.get('/api/snapshots/{revision}')
    def snapshot(revision: int, request: Request):
        session(request)
        return store.snapshot(revision)

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
