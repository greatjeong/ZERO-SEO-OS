"""First-page evidence collection. No simulated successes, posts or keyword promotion."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
import threading
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler
import uuid

from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, insert, select, update
from central_store import metadata
from server import NoRedirect, PinnedHTTPSConnection, PinnedHTTPSHandler, public_addresses

runs = Table('keyword_search_runs', metadata, Column('id', Text, primary_key=True),
             Column('created_at', Text, nullable=False), Column('record', Text, nullable=False))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def public_url(value):
    try:
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value) or '\\' in value:
            return None
        p = urlsplit(value)
        if p.scheme not in ('https', 'http') or not p.hostname or p.username is not None or p.password is not None or p.port not in (None, 80, 443) or '%' in p.netloc:
            return None
        host = p.hostname.encode('idna').decode('ascii')
        # Syntactic exclusion now; DNS pinning is mandatory before any page GET.
        import ipaddress
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if '.' not in host or host.endswith(('.localhost', '.local', '.internal')):
                return None
        return urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))
    except (ValueError, UnicodeError):
        return None


def platform_for(url):
    host = urlsplit(url).hostname.lower()
    if host in ('blog.naver.com', 'm.blog.naver.com'):
        return 'naver-blog'
    if host.endswith('.tistory.com'):
        return 'tistory'
    return 'unknown'


class PageSignals(HTMLParser):
    def __init__(self):
        super().__init__()
        self.wordpress = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and a.get('name', '').lower() == 'generator' and re.match(r'^WordPress(?:\s|$)', a.get('content', ''), re.I):
            self.wordpress = True
        if tag in ('link', 'script'):
            path = urlsplit(a.get('href') or a.get('src') or '').path
            if '/wp-content/' in path or '/wp-includes/' in path:
                self.wordpress = True


def inspect_wordpress(url):
    """Anonymous public HTTPS only. No proxy, auth, redirects or private-IP requests."""
    p = urlsplit(url)
    if p.scheme != 'https' or p.port not in (None, 443):
        return {'platform': 'unknown', 'reason': 'https_required'}
    connection = None
    try:
        addresses = public_addresses(p.hostname)
        connection = PinnedHTTPSConnection(p.hostname, addresses[0])
        connection.timeout = 6
        opener = build_opener(ProxyHandler({}), NoRedirect(), PinnedHTTPSHandler(connection))
        with opener.open(Request(url, headers={'User-Agent': 'ZERO-SEO-OS-Discovery/1.0', 'Accept': 'text/html', 'Accept-Encoding': 'identity'}), timeout=6) as response:
            if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', '').lower():
                return {'platform': 'unknown', 'reason': 'html_unavailable'}
            raw = response.read(524289)
            if len(raw) > 524288:
                return {'platform': 'unknown', 'reason': 'page_too_large'}
            parser = PageSignals()
            parser.feed(raw.decode('utf-8', errors='replace'))
            return {'platform': 'wordpress' if parser.wordpress else 'unknown',
                    'reason': 'wordpress_html_signals' if parser.wordpress else 'no_conclusive_signals'}
    except Exception:
        return {'platform': 'unknown', 'reason': 'page_check_failed'}
    finally:
        if connection:
            connection.close()


class SerpProvider:
    """Optional adapter; credentials stay server-side. No retries/pagination."""
    def __init__(self, key):
        self._key = key

    def search(self, engine, keyword):
        params = {'engine': engine, 'api_key': self._key, 'device': 'desktop'}
        if engine == 'google':
            params.update(q=keyword, start=0, hl='ko', gl='kr', google_domain='google.com')
        else:
            params.update(query=keyword, page=1, where='nexearch')
        request = Request('https://serpapi.com/search.json?' + urlencode(params),
                          headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=18) as response:
            if 'application/json' not in response.headers.get('Content-Type', ''):
                raise ValueError('invalid_provider_response')
            raw = response.read(2097153)
            if len(raw) > 2097152:
                raise ValueError('provider_response_too_large')
            return json.loads(raw)


def parse_response(engine, keyword, data):
    if not isinstance(data, dict) or data.get('error') or data.get('search_metadata', {}).get('status') != 'Success':
        raise ValueError('provider_incomplete')
    params = data.get('search_parameters', {})
    if params.get('engine') != engine or params.get('q' if engine == 'google' else 'query') != keyword:
        raise ValueError('query_mismatch')
    if engine == 'google':
        if str(params.get('start', 0)) != '0' or params.get('tbm') or params.get('udm'):
            raise ValueError('not_first_page')
        groups = ['organic_results']
    else:
        if str(params.get('page', 1)) != '1' or str(params.get('start', 1)) != '1' or params.get('where', 'nexearch') != 'nexearch':
            raise ValueError('not_first_integrated_page')
        # These are recognized sections only. Never recurse into ads, suggestions or page 2.
        groups = ['web_results', 'organic_results', 'blogs_results']
    page = data.get('serpapi_pagination', {}).get('current', 1)
    if str(page) != '1':
        raise ValueError('not_first_page')
    recognized = [g for g in groups if isinstance(data.get(g), list)]
    if not recognized:
        raise ValueError('unknown_result_schema')
    results, seen = [], set()
    for group in recognized:
        for item in data[group][:80]:
            if not isinstance(item, dict):
                continue
            url = public_url(item.get('link'))
            if not url or url in seen:
                continue
            seen.add(url)
            kind = platform_for(url)
            if kind == 'naver-blog':
                continue
            results.append({'id': str(uuid.uuid4()), 'url': url,
                            'blogOrigin': urlunsplit((urlsplit(url).scheme, urlsplit(url).netloc, '', '', '')),
                            'title': str(item.get('title', ''))[:500], 'section': group,
                            'sectionPosition': item.get('position') if type(item.get('position')) is int else None,
                            'platform': kind, 'evidence': 'tistory_hostname' if kind == 'tistory' else 'not_inspected'})
            if len(results) >= 80:
                break
    # Absence cannot be inferred from unknown CMS, omitted/unsupported SERP blocks or empty output.
    return {'engine': engine, 'status': 'retrieved', 'page': 1, 'checkedAt': stamp(),
            'provider': 'serpapi', 'coverage': 'recognized_sections_only', 'sections': recognized,
            'targetPresence': 'present' if any(r['platform'] == 'tistory' for r in results) else 'unknown',
            'results': results, 'searchVolume': None}


class Discovery:
    def __init__(self, store, provider=None):
        self.store, self.provider = store, provider
        self.gate = threading.BoundedSemaphore(1)
        with store.engine.begin() as db:
            store.lock(db, 901001)
            runs.create(db, checkfirst=True)

    def list(self):
        with self.store.engine.connect() as db:
            rows = db.execute(select(runs).order_by(runs.c.created_at.desc(), runs.c.id).limit(30)).mappings().all()
        return [json.loads(row['record']) for row in rows]

    def get(self, run_id):
        with self.store.engine.connect() as db:
            row = db.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
        if row is None:
            raise HTTPException(404, '검색 기록을 찾지 못했습니다.')
        return json.loads(row['record'])

    def create(self, payload):
        if set(payload) != {'keyword'} or not isinstance(payload.get('keyword'), str):
            raise HTTPException(400, '시작 키워드만 입력하세요.')
        keyword = payload['keyword'].strip()
        if not 1 <= len(keyword) <= 200 or any(ord(c) < 32 for c in keyword):
            raise HTTPException(400, '키워드는 1~200자로 입력하세요.')
        if not self.provider:
            raise HTTPException(503, '검색 API가 아직 연결되지 않았습니다. 검색 완료로 처리하지 않았습니다.')
        if not self.gate.acquire(blocking=False):
            raise HTTPException(429, '검색이 진행 중입니다. 기존 요청 결과를 먼저 확인하세요.')
        try:
            record = {'id': str(uuid.uuid4()), 'keyword': keyword, 'createdAt': stamp(),
                      'status': 'pending', 'engines': {e: {'engine': e, 'status': 'pending', 'results': [], 'targetPresence': 'unknown'} for e in ('naver', 'google')}}
            with self.store.engine.begin() as db:
                db.execute(insert(runs).values(id=record['id'], created_at=record['createdAt'], record=json.dumps(record, ensure_ascii=False)))
            def one(engine):
                try:
                    return parse_response(engine, keyword, self.provider.search(engine, keyword))
                except Exception:
                    # Never expose provider error text, request URLs or keys.
                    return {'engine': engine, 'status': 'unverified', 'checkedAt': stamp(), 'results': [], 'targetPresence': 'unknown', 'reason': 'request_or_schema_unverified'}
            with ThreadPoolExecutor(max_workers=2) as pool:
                record['engines'] = dict(zip(('naver', 'google'), pool.map(one, ('naver', 'google'))))
            record['status'] = 'retrieved' if all(r['status'] == 'retrieved' for r in record['engines'].values()) else 'incomplete'
            self.save(record)
            return record
        finally:
            self.gate.release()

    def save(self, record):
        with self.store.engine.begin() as db:
            db.execute(update(runs).where(runs.c.id == record['id']).values(record=json.dumps(record, ensure_ascii=False)))

    def inspect(self, run_id, result_id):
        if not self.gate.acquire(blocking=False):
            raise HTTPException(429, '검색 확인이 진행 중입니다.')
        try:
            record = self.get(run_id)
            for engine in record['engines'].values():
                for result in engine['results']:
                    if result['id'] != result_id:
                        continue
                    if result['platform'] != 'tistory':
                        finding = inspect_wordpress(result['url'])
                        result.update(platform=finding['platform'], evidence=finding['reason'], inspectedAt=stamp())
                    engine['targetPresence'] = 'present' if any(r['platform'] in ('tistory', 'wordpress') for r in engine['results']) else 'unknown'
                    self.save(record)
                    return record
            raise HTTPException(404, '검색 결과를 찾지 못했습니다.')
        finally:
            self.gate.release()
