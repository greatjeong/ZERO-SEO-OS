import unittest
from unittest.mock import Mock, patch
from fastapi import HTTPException
from central_article_html import render_markdown, preview
from central_article_transport import WordPressArticleTransport


class ArticleConversionTests(unittest.TestCase):
    def test_headings_lists_table_quote_and_code_preserve_text(self):
        result = render_markdown('# 제목\n\n## 답변\n**강조** 와 `code`\n\n- 하나\n- 둘\n\n1. 첫째\n2. 둘째\n\n| 항목 | 값 |\n| --- | --- |\n| 금액 | 100 |\n\n> 인용\n\n```html\n<script>bad()</script>\n```')
        for value in ('<h1>제목</h1>', '<h2>답변</h2>', '<strong>강조</strong>', '<code>code</code>', '<ul>', '<ol>', '<th>항목</th>', '<td>100</td>', '<blockquote>', '&lt;script&gt;'):
            self.assertIn(value, result)
        self.assertNotIn('<script>', result)

    def test_html_and_unsafe_links_are_never_executable(self):
        value = render_markdown('<img src=x onerror=alert(1)>\n\n[x](javascript:alert) [y](data:text/html,evil) [z](https://good.example/a?q=1&b=2)\n\n**<svg onload=evil>**')
        self.assertNotIn('<img', value);self.assertNotIn('<svg', value)
        self.assertNotIn('href="javascript:', value);self.assertNotIn('href="data:', value)
        self.assertIn('href="https://good.example/a?q=1&amp;b=2"', value)

    def test_unclosed_code_and_unsupported_markup_stay_visible(self):
        self.assertIn('abc', render_markdown('```\nabc'))
        self.assertIn('![alt]', render_markdown('![alt](https://example.com/image.png)'))
        for body in (None, True, 'a'*50001):
            with self.assertRaises(HTTPException):render_markdown(body)

    def test_preview_is_pure_and_draft_only(self):
        d={'id':'d','revision':3,'siteUrl':'https://wp.example','draft':{'title':'제목','body':'## 본문'}}
        self.assertEqual(preview(d)['contentHtml'],'<h2>본문</h2>')
        self.assertEqual(d['revision'],3);self.assertFalse(preview(d)['externalExecuted'])


class WordPressTransportTests(unittest.TestCase):
    def setUp(self):
        self.data={'url':'https://wp.example','username':'owner','password':'not-real'}
        self.vault=Mock();self.vault.load.return_value=(self.data,'generation')
        self.transport=WordPressArticleTransport(self.vault,'A-1')
        self.payload={'siteUrl':self.data['url'],'title':'원본 제목','bodyMarkdown':'## 새 본문\n\n<script>x</script>','status':'draft','requestId':'id'}

    @patch('central_article_transport.request_wp')
    @patch('central_article_transport.request_identity',return_value={'capabilities':{'edit_posts':True}})
    def test_authenticated_draft_conversion_uses_only_one_post(self, identity, request):
        request.return_value={'id':91,'status':'draft'}
        self.assertEqual(self.transport('create_draft',self.payload)['id'],91)
        request.assert_called_once()
        args=request.call_args.args
        self.assertEqual(args[3:5],('POST','/posts'));self.assertEqual(args[5]['status'],'draft')
        self.assertIn('<h2>새 본문</h2>',args[5]['content']);self.assertNotIn('<script>',args[5]['content'])

    @patch('central_article_transport.request_wp')
    @patch('central_article_transport.request_identity',return_value={'capabilities':{'edit_posts':False}})
    def test_no_permission_or_site_mismatch_never_posts(self, identity, request):
        with self.assertRaises(HTTPException):self.transport('create_draft',self.payload)
        self.payload['siteUrl']='https://other.example'
        with self.assertRaises(HTTPException):self.transport('create_draft',self.payload)
        request.assert_not_called()

    @patch('central_article_transport.request_wp')
    @patch('central_article_transport.request_identity',return_value={'capabilities':{'edit_posts':True}})
    def test_credentials_changed_before_post_blocks_write(self, identity, request):
        self.vault.load.side_effect=[(self.data,'old'),(self.data,'new')]
        with self.assertRaises(HTTPException):self.transport('create_draft',self.payload)
        request.assert_not_called()

    @patch('central_article_transport.request_wp',side_effect=TimeoutError('private upstream'))
    @patch('central_article_transport.request_identity',return_value={'capabilities':{'edit_posts':True}})
    def test_timeout_is_never_retried(self, identity, request):
        with self.assertRaises(TimeoutError):self.transport('create_draft',self.payload)
        self.assertEqual(request.call_count,1)

    @patch('central_article_transport.request_wp',return_value={'id':91,'status':'draft'})
    def test_readback_is_get_only_and_rejects_invalid_id(self, request):
        self.transport('read_draft',{'siteUrl':self.data['url'],'postId':91})
        self.assertEqual(request.call_args.args[3:5],('GET','/posts/91?context=edit'))
        for bad in (True,0,-1,'91',2**53):
            with self.assertRaises(HTTPException):self.transport('read_draft',{'siteUrl':self.data['url'],'postId':bad})
        self.assertEqual(request.call_count,1)
