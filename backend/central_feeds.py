"""Bounded anonymous RSS/Atom collection; title/tag candidates, never final keywords."""
from html import unescape
from html.parser import HTMLParser
import json
import re
import threading
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, ProxyHandler
import uuid
import xml.etree.ElementTree as ET

from fastapi import HTTPException
from sqlalchemy import Column, Table, Text, insert, select
from central_store import metadata
from central_discovery import public_url, stamp
from server import public_addresses, PinnedHTTPSConnection, PinnedHTTPSHandler, NoRedirect

collections = Table('keyword_feed_collections', metadata, Column('id', Text, primary_key=True),
                    Column('created_at', Text, nullable=False), Column('record', Text, nullable=False))
LIMIT = 1048576

class FeedError(Exception):
    def __init__(self, code): self.code = code


def checked_url(value):
    result = public_url(value)
    if not result or urlsplit(result).scheme != 'https' or urlsplit(result).port not in (None, 443):
        raise FeedError('public_https_required')
    return result


def fetch_public(url):
    url = checked_url(url)
    connection = None
    try:
        p = urlsplit(url)
        connection = PinnedHTTPSConnection(p.hostname, public_addresses(p.hostname)[0])
        connection.timeout = 6
        opener = build_opener(ProxyHandler({}), NoRedirect(), PinnedHTTPSHandler(connection))
        with opener.open(Request(url, headers={'User-Agent': 'ZERO-SEO-OS-Feed/1.0', 'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, text/html', 'Accept-Encoding': 'identity'}), timeout=6) as response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT: raise FeedError('response_too_large')
            return raw, response.headers.get('Content-Type', '')
    except HTTPError as e:
        code = 'access_restricted' if e.code in (401, 403, 429) else 'redirect_not_followed' if 300 <= e.code < 400 else 'http_error'
        e.close()
        raise FeedError(code) from None
    except FeedError: raise
    except Exception: raise FeedError('connection_failed') from None
    finally:
        if connection: connection.close()


class FeedLinks(HTMLParser):
    def __init__(self): super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and 'alternate' in (a.get('rel') or '').lower().split() and (a.get('type') or '').lower() in ('application/rss+xml', 'application/atom+xml'):
            href = a.get('href') or ''
            if not re.search(r'comments?|댓글', href + ' ' + (a.get('title') or ''), re.I): self.links.append(href)


def clean(text):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', text or ''))).strip()[:500]


def parse_feed(raw, feed_url, blog_url):
    if len(raw) > LIMIT: raise FeedError('response_too_large')
    try:
        text = raw.decode('utf-8-sig')  # explicit support; don't silently misdecode legacy/UTF16 XML
        if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', text, re.I): raise FeedError('unsafe_xml')
        root = ET.fromstring(text)
    except FeedError: raise
    except (ValueError, UnicodeError, ET.ParseError): raise FeedError('invalid_xml') from None
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    kind = local(root)
    if kind == 'rss':
        channel = root.find('channel')
        if channel is None: raise FeedError('unsupported_feed')
        entries = list(channel.findall('item'))
    elif root.tag == '{http://www.w3.org/2005/Atom}feed': entries = root.findall('{http://www.w3.org/2005/Atom}entry')
    else: raise FeedError('unsupported_feed')
    posts, candidates, index, seen_posts = [], [], {}, set()
    for entry in entries[:500]:
        title, link, published, tags = '', '', '', []
        for child in entry:
            name = local(child)
            if name == 'title': title = clean(''.join(child.itertext()))
            elif name == 'link':
                if kind == 'rss': link = (child.text or '').strip()
                elif child.get('rel', 'alternate') == 'alternate': link = child.get('href', '')
            elif name in ('pubDate', 'published', 'updated') and not published: published = clean(child.text)
            elif name == 'category':
                tag = clean(child.get('term') if kind != 'rss' else child.text)
                if tag: tags.append(tag)
        link = public_url(urljoin(feed_url, link)) if link else None
        # Prevent syndicated/external posts from being attributed to this blog.
        if not title or not link or urlsplit(link).netloc.lower() != urlsplit(blog_url).netloc.lower(): continue
        if link in seen_posts: continue
        seen_posts.add(link)
        posts.append({'title': title, 'url': link, 'published': published, 'tags': tags})
        for phrase, source_type in [(title, 'post_title')] + [(t, 'feed_category') for t in tags]:
            key = unicodedata.normalize('NFKC', phrase).casefold().strip()
            if key not in index:
                index[key] = len(candidates)
                candidates.append({'text': phrase, 'status': 'unreviewed', 'searchVolume': None, 'searchVerification': 'not_checked', 'sources': []})
            source = {'postUrl': link, 'feedUrl': feed_url, 'sourceType': source_type}
            sources = candidates[index[key]]['sources']
            if source not in sources: sources.append(source)
    return {'posts': posts, 'candidates': candidates, 'entryCount': len(entries), 'truncated': len(entries) > 500}


def collect_blog(blog_url, fetch=fetch_public):
    blog_url = checked_url(blog_url)
    origin = urlsplit(blog_url).netloc.lower()
    raw, content_type = fetch(blog_url)
    if 'html' not in content_type.lower():
        return {'feedUrl': blog_url, **parse_feed(raw, blog_url, blog_url)}
    parser = FeedLinks(); parser.feed(raw.decode('utf-8', errors='replace'))
    suggested = [urljoin(blog_url, v) for v in parser.links]
    base = blog_url.rstrip('/') + '/'
    suggested += [urljoin(base, 'rss'), urljoin(base, 'feed/')]
    attempted = set()
    for target in suggested:
        try: target = checked_url(target)
        except FeedError: continue
        if urlsplit(target).netloc.lower() != origin or target in attempted: continue
        if len(attempted) >= 3: break
        attempted.add(target)
        try:
            body, _ = fetch(target)
            return {'feedUrl': target, **parse_feed(body, target, blog_url)}
        except FeedError as e:
            if e.code in ('access_restricted', 'redirect_not_followed', 'connection_failed'): raise
    raise FeedError('feed_not_found_or_invalid')


class FeedCollector:
    def __init__(self, store):
        self.store = store; self.gate = threading.BoundedSemaphore(1)
        with store.engine.begin() as db:
            store.lock(db, 901001); collections.create(db, checkfirst=True)

    def list(self):
        with self.store.engine.connect() as db:
            rows = db.execute(select(collections).order_by(collections.c.created_at.desc(), collections.c.id).limit(20)).mappings().all()
        return [json.loads(row['record']) for row in rows]

    def create(self, payload, discovery_source=None):
        if set(payload) != {'blogUrl'} or not isinstance(payload.get('blogUrl'), str): raise HTTPException(400, '블로그 HTTPS 주소를 입력하세요.')
        try: blog = checked_url(payload['blogUrl'].strip())
        except FeedError: raise HTTPException(400, '인증정보 없는 공개 HTTPS 블로그 주소가 필요합니다.') from None
        if not self.gate.acquire(blocking=False): raise HTTPException(429, 'RSS 수집이 진행 중입니다.')
        try:
            record = {'id': str(uuid.uuid4()), 'blogUrl': blog, 'createdAt': stamp(), 'stage': 3, 'status': 'unverified', 'posts': [], 'candidates': []}
            if discovery_source is not None: record['searchSource'] = discovery_source
            try:
                record.update(collect_blog(blog))
                record['status'] = 'collected' if record['posts'] else 'empty'
            except FeedError as e: record['reason'] = e.code
            with self.store.engine.begin() as db:
                db.execute(insert(collections).values(id=record['id'], created_at=record['createdAt'], record=json.dumps(record, ensure_ascii=False)))
            return record
        finally: self.gate.release()
