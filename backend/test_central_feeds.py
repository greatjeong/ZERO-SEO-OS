from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from central_store import Store
from central_feeds import FeedError, FeedCollector, collect_blog, parse_feed, fetch_public

BLOG='https://blog.example/'
RSS=b'''<rss version="2.0"><channel><item><title>Taxi &amp; lost items</title><link>https://blog.example/one</link><category>Taxi</category></item><item><title>Taxi guide</title><link>https://blog.example/two</link><category>Taxi</category></item></channel></rss>'''
class FeedTests(unittest.TestCase):
    def test_titles_tags_deduplicate_with_provenance_and_no_filter(self):
        r=parse_feed(RSS,BLOG+'feed/',BLOG)
        self.assertEqual(len(r['posts']),2);self.assertEqual(len(r['candidates']),3)
        tag=next(c for c in r['candidates'] if c['text']=='Taxi')
        self.assertEqual(len(tag['sources']),2)
        self.assertIsNone(tag['searchVolume']);self.assertEqual(tag['status'],'unreviewed')

    def test_atom_relative_links(self):
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom title</title><link href="/post"/><category term="tag"/></entry></feed>'
        r=parse_feed(raw,BLOG+'atom',BLOG)
        self.assertEqual(r['posts'][0]['url'],BLOG+'post');self.assertEqual(len(r['candidates']),2)

    def test_external_and_duplicate_posts_not_misattributed(self):
        extra=b'<item><title>bad</title><link>https://else.example/post</link></item><item><title>duplicate</title><link>https://blog.example/one</link></item>'
        r=parse_feed(RSS.replace(b'</channel>',extra+b'</channel>'),BLOG+'feed',BLOG)
        self.assertEqual(len(r['posts']),2)

    def test_xml_and_size_errors(self):
        for raw in [b'<!DOCTYPE rss [<!ENTITY a "x">]><rss/>',b'<html/>',b'no xml',b'x'*1048577]:
            with self.assertRaises(FeedError):parse_feed(raw,BLOG,BLOG)

    def test_discovery_uses_same_origin_feed_and_ignores_comments(self):
        page=b'<link rel="alternate" type="application/rss+xml" href="https://evil.example/feed"><link rel="alternate" type="application/rss+xml" href="/comments/feed/"><link rel="alternate" type="application/rss+xml" href="/feed/">'
        seen=[]
        def fetch(url):
            seen.append(url)
            return (page,'text/html') if url==BLOG else (RSS,'application/rss+xml')
        r=collect_blog(BLOG,fetch)
        self.assertEqual(seen,[BLOG,BLOG+'feed/']);self.assertEqual(len(r['posts']),2)

    def test_denial_stops_collection(self):
        seen=[]
        def fetch(url):
            seen.append(url)
            if url==BLOG:return b'<html/>','text/html'
            raise FeedError('access_restricted')
        with self.assertRaises(FeedError):collect_blog(BLOG,fetch)
        self.assertEqual(len(seen),2)

    def test_private_dns_never_opens_connection(self):
        with patch('central_feeds.public_addresses',side_effect=ValueError()),patch('central_feeds.build_opener') as op:
            with self.assertRaises(FeedError):fetch_public(BLOG)
            op.assert_not_called()

    def test_records_persist_failures_do_not_erase_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector=FeedCollector(Store(Path(tmp)))
            with patch('central_feeds.collect_blog',return_value={'feedUrl':BLOG+'feed/',**parse_feed(RSS,BLOG+'feed/',BLOG)}):
                record=collector.create({'blogUrl':BLOG})
            with patch('central_feeds.collect_blog',side_effect=FeedError('connection_failed')):
                failed=collector.create({'blogUrl':BLOG})
            self.assertEqual(record['status'],'collected');self.assertEqual(failed['status'],'unverified')
            self.assertEqual(len(FeedCollector(Store(Path(tmp))).list()),2)
            self.assertEqual(failed['candidates'],[])

    def test_api_auth_csrf_and_no_search_key_requirement(self):
        from fastapi.testclient import TestClient
        from central import Settings, create_app
        from central_auth import hash_password
        with tempfile.TemporaryDirectory() as tmp:
            origin='https://zero.example'
            with TestClient(create_app(Settings(origin,Path(tmp),hash_password('test-only-password-long-enough'))),base_url=origin) as client:
                self.assertEqual(client.get('/api/feed-collections').status_code,401)
                self.assertEqual(client.post('/api/feed-collections',json={'blogUrl':BLOG}).status_code,401)
                login=client.post('/api/login',json={'password':'test-only-password-long-enough'},headers={'Origin':origin}).json()
                self.assertEqual(client.post('/api/feed-collections',json={'blogUrl':BLOG},headers={'Origin':origin}).status_code,403)
                with patch('central_feeds.collect_blog',return_value={'feedUrl':BLOG+'feed/',**parse_feed(RSS,BLOG+'feed/',BLOG)}):
                    response=client.post('/api/feed-collections',json={'blogUrl':BLOG},headers={'Origin':origin,'X-CSRF-Token':login['csrf']})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['status'],'collected')
                self.assertEqual(len(client.get('/api/feed-collections').json()['collections']),1)
