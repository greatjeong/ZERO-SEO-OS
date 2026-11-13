"""ZERO SEO OS local-only WordPress connector. Python 3.11+, no packages."""
import base64
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

CONNECTOR_VERSION = '0.2.4'
ORIGIN = 'http://127.0.0.1:5173'
HOST = '127.0.0.1:8765'
STATE_DB = Path(__file__).resolve().parent / '.state' / 'test-drafts.sqlite3'
TEST_TITLE = '[ZERO SEO OS] 연결 테스트 초안'
TEST_CONTENT = '<p>ZERO SEO OS와 워드프레스의 초안 저장 연결을 확인하기 위한 테스트 글입니다.</p>'


class VerificationError(Exception):
    pass


def normalize_url(raw):
    try:
        p = urlsplit(raw.strip())
        if (p.scheme != 'https' or not p.hostname or p.username is not None
                or p.password is not None or p.query or p.fragment or p.port not in (None, 443)
                or '%' in p.netloc or '\\' in raw or any(ord(c) < 33 for c in raw)):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii')
        return urlunsplit(('https', host, p.path.rstrip('/'), '', ''))
    except (ValueError, AttributeError, UnicodeError):
        raise VerificationError('유효한 HTTPS 사이트 주소가 필요합니다.') from None


def public_addresses(hostname):
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise VerificationError('공개 인터넷 사이트만 연결할 수 있습니다. 내부 주소는 차단됩니다.')
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address):
        super().__init__(hostname, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated address, while checking the original TLS hostname.
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def request_wp(url, username, password, method, endpoint, body=None):
    parsed = urlsplit(url)
    addresses = public_addresses(parsed.hostname)
    conn = PinnedHTTPSConnection(parsed.hostname, addresses[0])
    authorization = base64.b64encode(f'{username}:{password}'.encode()).decode('ascii')
    try:
        path = parsed.path + '/wp-json/wp/v2' + endpoint
        # Authentication responses must be freshly fetched, as in the successful diagnostic.
        # Keep POST endpoints unchanged: writes must never be retried or cache-busted.
        if method == 'GET':
            path += ('&' if '?' in path else '?') + '_zero_check=' + secrets.token_hex(8)
        headers = {
            'Cache-Control': 'no-cache, no-store', 'Pragma': 'no-cache',
            'Authorization': 'Basic ' + authorization,
            'Accept': 'application/json', 'User-Agent': 'ZERO-SEO-OS/' + CONNECTOR_VERSION,
        }
        if body is None:
            conn.request(method, path, headers=headers)
        else:
            headers['Content-Type'] = 'application/json'
            conn.request(method, path, body=json.dumps(body).encode('utf-8'), headers=headers)
        response = conn.getresponse()
        if response.status in (401, 403):
            # Surface only a bounded WP error code, never upstream messages or credentials.
            code = ''
            try:
                error_data = json.loads(response.read(16385))
                candidate = error_data.get('code') if isinstance(error_data, dict) else None
                if isinstance(candidate, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', candidate):
                    code = ' · ' + candidate
            except (ValueError, UnicodeError):
                pass
            raise VerificationError(f'워드프레스 HTTP {response.status}{code} · 인증 또는 사용자 조회가 거부됐습니다.')
        if response.status != (201 if method == 'POST' else 200):
            raise VerificationError(f'워드프레스 응답 HTTP {response.status}. 리다이렉트는 허용하지 않습니다.')
        if 'application/json' not in (response.getheader('Content-Type') or '').lower():
            raise VerificationError('워드프레스 JSON 응답이 아닙니다.')
        raw = response.read(262145)
        if len(raw) > 262144:
            raise VerificationError('워드프레스 응답 크기가 제한을 초과했습니다.')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise VerificationError('워드프레스 응답 형식이 올바르지 않습니다.')
        return data
    finally:
        conn.close()


def request_identity(url, username, password):
    data = request_wp(url, username, password, 'GET', '/users/me?context=edit')
    if (type(data.get('id')) is not int or data['id'] <= 0 or data.get('username') != username):
        raise VerificationError('인증된 워드프레스 사용자 응답을 확인하지 못했습니다.')
    return data


def configured_site(payload):
    if not isinstance(payload, dict) or set(payload) != {'site', 'url'}:
        raise VerificationError('사이트 ID와 주소만 전송하세요.')
    site = payload['site']
    if site not in ('A-1', 'A-2') or not isinstance(payload['url'], str):
        raise VerificationError('사이트 ID 또는 주소가 올바르지 않습니다.')
    prefix = 'ZERO_WP_' + site.replace('-', '')
    configured_url = os.environ.get(prefix + '_URL', '')
    username = os.environ.get(prefix + '_USER', '')
    password = os.environ.get(prefix + '_APP_PASSWORD', '')
    if not configured_url or not username or not password:
        raise VerificationError(f'서버의 {prefix}_URL / _USER / _APP_PASSWORD 환경변수를 설정하고 재시작하세요.')
    url = normalize_url(payload['url'])
    if url != normalize_url(configured_url):
        raise VerificationError('등록 주소와 서버에 허용된 사이트 주소가 다릅니다.')
    if ':' in username or any(c in username + password for c in '\r\n'):
        raise VerificationError('서버 인증 설정 형식이 올바르지 않습니다.')
    return site, url, username, password


def verify(payload, include_permissions=False):
    site, url, username, password = configured_site(payload)
    identity = request_identity(url, username, password)
    result = {'site': site, 'url': url, 'verified': True,
              'checkedAt': datetime.now(timezone.utc).isoformat()}
    if include_permissions:
        caps = identity.get('capabilities') if isinstance(identity, dict) else None
        # Missing entire capability data is unknown, never an inferred grant.
        def capability(name):
            if not isinstance(caps, dict):
                return None
            value = caps.get(name, False)
            return value if type(value) is bool else None
        result['permissions'] = {'editPosts': capability('edit_posts'),
                                 'publishPosts': capability('publish_posts')}
        result['permissionBasis'] = 'wordpress-user-capabilities'
    return result


def validate_draft(data, expected_id=None):
    post_id = data.get('id') if isinstance(data, dict) else None
    if type(post_id) is not int or post_id <= 0 or (expected_id is not None and post_id != expected_id):
        raise VerificationError('초안 글 ID를 확인하지 못했습니다. 워드프레스 글 목록을 확인하세요.')
    if data.get('status') != 'draft':
        raise VerificationError(f'글 ID {post_id}의 상태가 초안이 아닙니다. 워드프레스 관리자에서 즉시 확인하세요. 추가 생성하지 않습니다.')
    return post_id


def test_draft(payload):
    site, url, username, password = configured_site(payload)
    identity = request_identity(url, username, password)
    caps = identity.get('capabilities')
    if not isinstance(caps, dict) or caps.get('edit_posts') is not True:
        raise VerificationError('글 작성 권한을 확인하지 못해 초안을 만들지 않았습니다.')
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    # Key by canonical URL, so switching A-1/A-2 or credentials cannot duplicate this test.
    with closing(sqlite3.connect(STATE_DB, timeout=5)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS drafts (url TEXT PRIMARY KEY, post_id INTEGER, created_at TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT post_id, created_at FROM drafts WHERE url = ?', (url,)).fetchone()
        if row is None:
            created_at = datetime.now(timezone.utc).isoformat()
            # Commit intent BEFORE sending the write request. Never automatically retry a write.
            db.execute('INSERT INTO drafts(url, post_id, created_at) VALUES (?, NULL, ?)', (url, created_at))
        db.commit()
    if row is not None:
        post_id, created_at = row
        if post_id is None:
            raise VerificationError('이 사이트의 초안 저장이 진행 중이거나 이전 결과가 불확실합니다. 중복 생성을 막았습니다. 워드프레스 글 목록에서 테스트 초안을 먼저 확인하세요.')
        # Re-check the existing post, rather than claiming a cached status is still current.
        data = request_wp(url, username, password, 'GET', f'/posts/{post_id}?context=edit')
        validate_draft(data, post_id)
        reused = True
    else:
        try:
            data = request_wp(url, username, password, 'POST', '/posts', {
                'title': TEST_TITLE, 'content': TEST_CONTENT, 'status': 'draft',
                'comment_status': 'closed', 'ping_status': 'closed',
            })
            post_id = validate_draft(data)
            with closing(sqlite3.connect(STATE_DB, timeout=5)) as db:
                db.execute('UPDATE drafts SET post_id = ? WHERE url = ?', (post_id, url))
                db.commit()
            # A separate read must confirm the saved status before showing success.
            data = request_wp(url, username, password, 'GET', f'/posts/{post_id}?context=edit')
            validate_draft(data, post_id)
            reused = False
        except Exception as error:
            detail = str(error) if isinstance(error, VerificationError) else '통신 또는 응답 처리 실패'
            raise VerificationError(f'{detail} · 저장 결과가 불확실할 수 있어 재생성을 차단했습니다. 워드프레스 글 목록을 확인하세요.') from None
    return {'site': site, 'url': url, 'draftConfirmed': True, 'postId': post_id,
            'status': 'draft', 'reused': reused, 'createdAt': created_at,
            'checkedAt': datetime.now(timezone.utc).isoformat()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Do not log requests, payloads, or credentials.
        pass

    def allowed(self):
        return self.headers.get('Host') == HOST and self.headers.get('Origin') == ORIGIN

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        if self.allowed():
            self.send_header('Access-Control-Allow-Origin', ORIGIN)
            self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self.allowed() or self.path not in ('/api/sites/verify', '/api/sites/permissions', '/api/sites/test-draft', '/api/storage'):
            self.reply(403, {'verified': False})
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', ORIGIN)
        self.send_header('Access-Control-Allow-Methods', 'POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_POST(self):
        if not self.allowed():
            self.reply(403, {'verified': False, 'message': '허용되지 않은 요청입니다.'})
            return
        if self.path not in ('/api/sites/verify', '/api/sites/permissions', '/api/sites/test-draft', '/api/storage'):
            self.reply(404, {'verified': False})
            return
        try:
            self.connection.settimeout(15)
            if self.headers.get('Transfer-Encoding'):
                raise VerificationError('청크 요청은 허용하지 않습니다.')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= (5 * 1024 * 1024 if self.path == '/api/storage' else 4096) or self.headers.get('Content-Type') != 'application/json':
                raise VerificationError('JSON 요청 크기 또는 형식이 올바르지 않습니다.')
            payload = json.loads(self.rfile.read(size))
            if self.path == '/api/storage':
                from storage import snapshot
                result = snapshot(payload)
            elif self.path == '/api/sites/test-draft':
                result = test_draft(payload)
            else:
                result = verify(payload, include_permissions=True) if self.path == '/api/sites/permissions' else verify(payload)
            self.reply(200, result)
        except VerificationError as error:
            self.reply(400, {'verified': False, 'message': str(error)})
        except (ValueError, UnicodeError):
            self.reply(400, {'verified': False, 'message': '요청 또는 워드프레스 JSON 형식 오류입니다.'})
        except Exception:
            # Never return upstream content or exception strings containing secrets.
            self.reply(502, {'verified': False, 'message': '연결 실패. DNS·HTTPS 인증서·방화벽·응답 시간을 확인하세요.'})


if __name__ == '__main__':
    print('ZERO SEO OS connector v' + CONNECTOR_VERSION + ': http://' + HOST + ' (local only; fresh authentication requests)')
    httpd = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
