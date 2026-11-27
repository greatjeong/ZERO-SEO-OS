"""WordPress original-draft transport. Available for explicit injection, not enabled by default."""
from fastapi import HTTPException
from central_article_html import render_markdown
from server import request_identity, request_wp


class WordPressArticleTransport:
    def __init__(self, vault, slot):
        self.vault, self.slot = vault, slot

    def __call__(self, operation, payload):
        if operation not in ('create_draft', 'read_draft'):
            raise HTTPException(400, '지원하지 않는 원본 초안 작업입니다.')
        data, generation = self.vault.load(self.slot)
        if payload.get('siteUrl') != data['url']:
            raise HTTPException(409, '원본 문서와 등록 사이트 주소가 다릅니다.')
        if operation == 'create_draft':
            if payload.get('status') != 'draft' or not isinstance(payload.get('title'), str) or not payload['title'].strip() or len(payload['title']) > 200:
                raise HTTPException(400, '초안 제목과 상태를 확인하세요.')
            content = render_markdown(payload.get('bodyMarkdown'))
            if not content:
                raise HTTPException(400, '빈 본문은 전송할 수 없습니다.')
            identity = request_identity(data['url'], data['username'], data['password'])
            if not isinstance(identity.get('capabilities'), dict) or identity['capabilities'].get('edit_posts') is not True:
                raise HTTPException(403, '글 작성 권한을 확인하지 못했습니다.')
            current, current_generation = self.vault.load(self.slot)
            if generation != current_generation or current['url'] != data['url']:
                raise HTTPException(409, '확인 중 사이트 인증정보가 변경됐습니다.')
            # No retry. ArticleDrafts commits an intent before calling this transport.
            return request_wp(data['url'], data['username'], data['password'], 'POST', '/posts',
                              {'title': payload['title'], 'content': content, 'status': 'draft',
                               'comment_status': 'closed', 'ping_status': 'closed'})
        post_id = payload.get('postId')
        if type(post_id) is not int or not 0 < post_id <= 2**53 - 1:
            raise HTTPException(400, '조회할 글 ID를 확인하세요.')
        result = request_wp(data['url'], data['username'], data['password'], 'GET', f'/posts/{post_id}?context=edit')
        current, current_generation = self.vault.load(self.slot)
        if generation != current_generation or current['url'] != data['url']:
            raise HTTPException(409, '조회 중 사이트 인증정보가 변경됐습니다.')
        return result
