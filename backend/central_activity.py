"""Read-only activity summary of existing evidence, not an automation task runner."""
import json
from sqlalchemy import select
from central_discovery import runs, stamp
from central_feeds import collections
from central_keyword_bank import events, keywords

EVENTS = {
    'candidate_staged': ('검토 후보 등록', 'review', '검색·선별 전 후보입니다.'),
    'source_added': ('키워드 출처 추가', 'recorded', '원본과 기존 상태를 유지했습니다.'),
    'search_checked': ('양쪽 검색 결과 기록', 'review', '블로그 유형과 선별 결과는 별도로 확인하세요.'),
    'search_unverified': ('키워드 재검증 미완료', 'attention', '이전 원본을 유지했습니다. 검색 연결 상태와 근거를 확인하세요.'),
    'manual_active': ('키워드 활성 선택', 'recorded', '수동 검토 결과이며 검색량 조건은 적용하지 않았습니다.'),
    'manual_excluded': ('활성 목록에서 제외', 'recorded', '원본·출처·변경 이력은 보존됩니다.'),
    'original_article_handoff': ('원본 글 작성 준비로 연결', 'recorded', '연결 기록입니다. 실제 AI 글 생성·저장·발행은 실행하지 않았습니다.'),
}
FEED_REASONS = {
    'public_https_required': '공개 HTTPS 블로그 주소를 확인하세요.',
    'connection_failed': '연결 결과를 확인하지 못했습니다. 사이트 접근과 서버 통신 상태를 확인하세요.',
    'access_restricted': '접근 제한 응답입니다. 자동 재시도하지 않고 수집을 멈췄습니다.',
    'redirect_not_followed': '주소 이동이 발생했습니다. 최종 공개 HTTPS 주소를 확인하세요.',
    'response_too_large': '응답 크기 제한을 초과했습니다.',
    'unsafe_xml': '지원하지 않는 XML 선언이 있어 수집하지 않았습니다.',
    'invalid_xml': 'UTF-8 RSS·Atom 형식인지 확인하세요.',
    'unsupported_feed': '지원하는 RSS2·Atom 피드가 아닙니다.',
    'feed_not_found_or_invalid': '확인한 경로에서 유효한 피드를 찾지 못했습니다. 사이트 전체에 피드가 없다는 뜻은 아닙니다.',
}


def activity(store):
    entries, incomplete = [], []
    more = False
    with store.engine.connect() as db:
        def rows(table, column, time_column, source):
            nonlocal more
            try:
                result = db.execute(select(table).order_by(time_column.desc(), table.c.id).limit(21)).mappings().all()
                more |= len(result) > 20
                parsed = [(r, json.loads(r[column])) for r in result[:20]]
                if any(not isinstance(value, dict) for _, value in parsed): raise ValueError('invalid_record')
                return parsed
            except (ValueError, TypeError, KeyError):
                incomplete.append(source)
                return []

        for raw, run in rows(runs, 'record', runs.c.created_at, 'search'):
            complete = run.get('status') == 'retrieved'
            found = any(e.get('targetPresence') == 'present' for e in run.get('engines', {}).values())
            pending = run.get('status') == 'pending'
            entries.append({'id': 'search:' + raw['id'], 'source': 'search', 'sourceId': raw['id'], 'stage': 2,
                'at': raw['created_at'], 'title': run.get('keyword', '')[:200],
                'label': '양쪽 검색 결과 수신' if complete else '검색 결과 미확정' if pending else '검색 확인 미완료',
                'state': 'review' if complete else 'attention', 'target': 'discovery',
                'message': ('대상 블로그 유형을 찾았습니다. 선별 전 근거를 확인하세요.' if found else '사이트 유형·수집 범위를 확인하세요. 미확인을 노출 없음으로 처리하지 않습니다.') if complete else '양쪽 결과가 확인되지 않았습니다. 요청 중이거나 중단된 기록일 수 있으며, 자동 재검색하지 않습니다.'})

        for raw, feed in rows(collections, 'record', collections.c.created_at, 'rss'):
            status = feed.get('status')
            entries.append({'id': 'rss:' + raw['id'], 'source': 'rss', 'sourceId': raw['id'], 'stage': 3,
                'at': raw['created_at'], 'title': feed.get('blogUrl', '')[:200], 'target': 'feeds',
                'label': 'RSS 후보 수집 기록' if status == 'collected' else '피드 내 수집 글 없음' if status == 'empty' else 'RSS 수집 미완료',
                'state': 'recorded' if status == 'collected' else 'review' if status == 'empty' else 'attention',
                'message': f"글 {len(feed.get('posts', []))}개·검토 전 후보 {len(feed.get('candidates', []))}개. 검색량·노출 검증과 최종 선별 전입니다." if status == 'collected' else '피드에서 수집 가능한 글이 없었습니다. 이전 기록은 유지됩니다.' if status == 'empty' else FEED_REASONS.get(feed.get('reason'), '수집 결과를 확인하지 못했습니다. 원래 수집 기록을 확인하세요.')})

        history = rows(events, 'record', events.c.at, 'keyword')
        ids = list({r['keyword_id'] for r, _ in history})
        names = {}
        if ids:
            for raw in db.execute(select(keywords).where(keywords.c.id.in_(ids))).mappings():
                try: names[raw['id']] = json.loads(raw['record']).get('keyword', '')[:200]
                except (ValueError, TypeError, KeyError): incomplete.append('keyword')
        for raw, event in history:
            label, state, message = EVENTS.get(event.get('event'), ('키워드 변경 기록', 'review', '개별 키워드의 변경 이력을 확인하세요.'))
            entries.append({'id': 'keyword:' + raw['id'], 'source': 'keyword', 'sourceId': raw['keyword_id'], 'stage': 6 if event.get('event') == 'original_article_handoff' else 4 if event.get('event') == 'candidate_staged' else 5,
                            'at': raw['at'], 'title': names.get(raw['keyword_id'], '키워드 기록'), 'label': label, 'state': state, 'message': message, 'target': 'bank'})
    entries.sort(key=lambda r: (r['at'], r['id']), reverse=True)
    return {'checkedAt': stamp(), 'scope': 'latest_20_per_source', 'hasEarlierRecords': more,
            'incompleteSources': sorted(set(incomplete)), 'items': entries,
            'counts': {'records': len(entries), 'attention': sum(r['state'] == 'attention' for r in entries), 'review': sum(r['state'] == 'review' for r in entries)}}
