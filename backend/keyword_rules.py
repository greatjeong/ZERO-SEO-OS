"""Accepted selection policy. Pure evaluation; no provider/network calls."""
RULE_VERSION = 'naver-volume-any-target-v1'

def volume_tier(value):
    if type(value) is not int or value < 500: return None
    return 1 if value < 3000 else 2 if value < 10000 else 3

def evaluate(row):
    volume = row.get('searchVolume') or {}
    naver = volume.get('naver') or {} if isinstance(volume, dict) else {}
    value = naver.get('monthly')
    valid_volume = type(value) is int and value >= 0 and bool(naver.get('source')) and bool(naver.get('checkedAt'))
    tier = volume_tier(value) if valid_volume else None
    engines = (row.get('evidence') or {}).get('engines') or {}
    complete = row.get('verification', 'both_retrieved') == 'both_retrieved' and all(engines.get(e, {}).get('status') == 'retrieved' and engines.get(e, {}).get('page') == 1 for e in ('naver', 'google'))
    matches = [{'engine': e, **r} for e in ('naver', 'google') for r in engines.get(e, {}).get('results', [])
               if engines.get(e, {}).get('status') == 'retrieved' and engines.get(e, {}).get('page') == 1 and r.get('platform') in ('tistory', 'wordpress')]
    reasons = []
    if not valid_volume: reasons.append('네이버 월간 검색량 미확인')
    elif tier is None: reasons.append('네이버 월간 검색량 500 미만')
    if not complete: reasons.append('네이버·구글 1페이지 조회 미완료')
    if not matches: reasons.append('1페이지 티스토리·워드프레스 노출 미확인')
    if row.get('manualExclusion'): reasons.append('사용자가 사용 목록에서 제외')
    return {'ruleVersion': RULE_VERSION, 'eligible': not reasons, 'tier': tier, 'naverMonthly': value if valid_volume else None, 'reasons': reasons, 'matches': matches}

def enforce(row, promote=False):
    result = evaluate(row)
    row['selection'] = result
    row['selectionMode'] = RULE_VERSION
    row['reviewRequired'] = not result['eligible']
    if not result['eligible']: row['status'] = 'excluded'
    elif promote: row['status'] = 'active'
    return row
