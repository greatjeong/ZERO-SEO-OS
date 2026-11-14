"""Private central foundation: login, versioned workspace and backup import.
Encrypted WordPress credentials and explicit read-only verification; no automatic migration.
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

VERSION = '0.3.4-durable-draft'
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
    wp_key: str | None = field(default=None, repr=False)
    search_key: str | None = field(default=None, repr=False)

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
        return cls(origin.rstrip('/'), Path(directory) if directory else None, encoded, database_url=database, wp_key=os.environ.get('ZERO_WP_ENCRYPTION_KEY'), search_key=os.environ.get('ZERO_SERPAPI_KEY'))


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
    from central_wordpress import WordPressVault
    vault = WordPressVault(store, cfg.wp_key) if cfg.wp_key else None
    from central_drafts import DraftHistory
    drafts = DraftHistory(store, vault)
    from central_draft_save import DraftSaver
    draft_saver = DraftSaver(store, vault)
    from central_discovery import Discovery, SerpProvider
    discovery = Discovery(store, SerpProvider(cfg.search_key) if cfg.search_key else None)
    from central_feeds import FeedCollector
    feeds = FeedCollector(store)
    from central_keyword_bank import KeywordBank
    bank = KeywordBank(store, discovery)
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
        return {'version': VERSION, 'mode': 'private-owner', 'database': store.kind, 'wordpressEnabled': vault is not None, 'searchEnabled': discovery.provider is not None}

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

    def require_vault():
        if vault is None:
            raise HTTPException(503, '워드프레스 암호화 저장 키가 서버에 설정되지 않았습니다.')
        return vault

    @app.put('/api/wordpress/{slot}/credentials')
    async def save_credentials(slot: str, request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return await run_in_threadpool(require_vault().save, slot, payload)

    @app.post('/api/wordpress/{slot}/verify')
    def verify_wordpress(slot: str, request: Request):
        session(request, write=True)
        return require_vault().verify(slot)

    @app.get('/api/draft-history')
    def draft_records(request: Request):
        session(request)
        return {'records': drafts.list()}

    @app.post('/api/draft-history/preview')
    async def preview_draft_records(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return {'records': drafts.preview(payload), 'wordpressChanged': False}

    @app.post('/api/draft-history/import')
    async def import_draft_records(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return await run_in_threadpool(drafts.save, payload)

    @app.post('/api/wordpress/{slot}/draft-history/{fingerprint}/check')
    def check_draft_record(slot: str, fingerprint: str, request: Request):
        session(request, write=True)
        return drafts.check(slot, fingerprint)

    @app.get('/api/wordpress/{slot}/test-draft')
    def test_draft_state(slot: str, request: Request):
        session(request)
        return draft_saver.state(slot)

    @app.post('/api/wordpress/{slot}/test-draft')
    async def save_test_draft(slot: str, request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return await run_in_threadpool(draft_saver.create, slot, payload)

    @app.post('/api/wordpress/{slot}/test-draft/check')
    def recheck_test_draft(slot: str, request: Request):
        session(request, write=True)
        return draft_saver.check(slot)

    @app.get('/api/activity')
    def recent_activity(request: Request):
        session(request)
        from central_activity import activity
        return activity(store)

    @app.get('/api/keyword-bank')
    def keyword_bank(request: Request, offset: int = 0):
        session(request)
        return bank.list(offset)

    @app.get('/api/keyword-bank/export')
    def export_keyword_bank(request: Request):
        session(request)
        return bank.export()

    @app.post('/api/keyword-bank/stage')
    async def stage_candidates(request: Request):
        session(request, write=True)
        return await run_in_threadpool(bank.stage, await read_json(request))

    @app.get('/api/keyword-bank/{key}/history')
    def keyword_history(key: str, request: Request):
        session(request)
        return {'events': bank.history(key)}

    @app.post('/api/keyword-bank/{key}/check')
    async def check_keyword(key: str, request: Request):
        session(request, write=True)
        return await run_in_threadpool(bank.check, key, await read_json(request))

    @app.post('/api/keyword-bank/{key}/evidence')
    async def attach_keyword_evidence(key: str, request: Request):
        session(request, write=True)
        return await run_in_threadpool(bank.attach, key, await read_json(request))

    @app.post('/api/keyword-bank/{key}/review')
    async def review_keyword(key: str, request: Request):
        session(request, write=True)
        return await run_in_threadpool(bank.review, key, await read_json(request))

    @app.post('/api/keyword-bank/{key}/handoff')
    async def handoff_keyword(key: str, request: Request):
        session(request, write=True)
        return await run_in_threadpool(bank.handoff, key, await read_json(request))

    @app.get('/api/article-preparations')
    def article_preparations(request: Request):
        session(request)
        return {'preparations': bank.queue()}

    @app.post('/api/feed-collections/from-discovery')
    async def feed_from_discovery(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        if set(payload) != {'runId', 'resultId'} or not all(isinstance(v, str) for v in payload.values()):
            raise HTTPException(400, '검색 출처를 확인하세요.')
        run = discovery.get(payload['runId'])
        if run['status'] != 'retrieved':
            raise HTTPException(409, '양쪽 검색 결과를 먼저 확인하세요.')
        for engine in run['engines'].values():
            for result in engine['results']:
                if result['id'] == payload['resultId'] and result['platform'] in ('wordpress', 'tistory'):
                    return await run_in_threadpool(feeds.create, {'blogUrl': result['blogOrigin']}, {'runId': run['id'], 'resultId': result['id'], 'keyword': run['keyword']})
        raise HTTPException(409, '블로그 유형을 먼저 확인하세요.')

    @app.get('/api/feed-collections')
    def feed_history(request: Request):
        session(request)
        return {'collections': feeds.list()}

    @app.post('/api/feed-collections')
    async def collect_feed(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return await run_in_threadpool(feeds.create, payload)

    @app.get('/api/discovery')
    def discovery_history(request: Request):
        session(request)
        return {'configured': discovery.provider is not None, 'runs': discovery.list()}

    @app.post('/api/discovery')
    async def discover_keyword(request: Request):
        session(request, write=True)
        payload = await read_json(request)
        return await run_in_threadpool(discovery.create, payload)

    @app.post('/api/discovery/{run_id}/results/{result_id}/inspect')
    def inspect_discovery_result(run_id: str, result_id: str, request: Request):
        session(request, write=True)
        return discovery.inspect(run_id, result_id)

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
