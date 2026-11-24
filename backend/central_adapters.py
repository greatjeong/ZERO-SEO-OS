"""Provider-neutral bounded contracts. No credentials, network or default live adapter."""
from datetime import datetime
from fastapi import HTTPException


def text(value, limit, allow_empty=False):
    if not isinstance(value, str) or len(value)>limit or (not allow_empty and not value.strip()):
        raise HTTPException(400, '입력 길이·형식을 확인하세요.')
    return value.strip()


def generated(value, max_chars=50000):
    if (not isinstance(value, dict) or set(value)-{'title','body','unverifiedClaims'}
        or not isinstance(value.get('title'),str) or not 1<=len(value['title'].strip())<=200
        or not isinstance(value.get('body'),str) or not 1<=len(value['body'].strip())<=max_chars
        or not isinstance(value.get('unverifiedClaims',[]),list)
        or len(value.get('unverifiedClaims',[]))>50
        or any(not isinstance(v,str) or len(v)>500 for v in value.get('unverifiedClaims',[]))):
        raise HTTPException(502,'AI 응답 형식·길이 미확인 · 기존 원고 유지')
    return {k:value.get(k,[]) for k in ('title','body','unverifiedClaims')}


def volume_result(keyword, result):
    if (not isinstance(result,dict) or set(result)!={'keyword','monthly','source','checkedAt'}
        or result['keyword']!=keyword or (result['monthly'] is not None and
        (type(result['monthly']) is not int or not 0<=result['monthly']<=2**53-1))):
        raise HTTPException(502,'검색량 응답 미확인 · 실제 검색어와 정수/미확인 값을 확인하세요.')
    text(result['source'],200)
    try:
        checked=datetime.fromisoformat(result['checkedAt'].replace('Z','+00:00'))
        if checked.tzinfo is None:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise HTTPException(502,'검색량 확인 시각 미확인') from None
    return dict(result)


class GenerationAdapter:
    """Explicitly injected transport. The production app does not instantiate one."""
    def __init__(self, transport, max_chars=50000):self.transport,self.max_chars=transport,max_chars
    def __call__(self, brief):
        try:return generated(self.transport(brief),self.max_chars)
        except HTTPException:raise
        except Exception:raise HTTPException(502,'AI 연결 결과 미확인 · 자동 재시도하지 않습니다.') from None


class VolumeAdapter:
    def __init__(self, transport):self.transport=transport
    def lookup(self, keyword):
        try:return volume_result(keyword,self.transport(keyword))
        except HTTPException:raise
        except Exception:raise HTTPException(502,'검색량 연결 결과 미확인') from None


def quality_report(document):
    """Transparent editorial checks, never a fact-check or ranking score."""
    draft=document.get('draft') or {};title=draft.get('title','');body=draft.get('body','')
    lines=[v.strip() for v in body.splitlines() if len(v.strip())>=30]
    findings=[]
    if not title.strip():findings.append({'code':'missing_title','message':'제목을 입력하세요.'})
    if not body.strip():findings.append({'code':'missing_body','message':'본문을 입력하세요.'})
    if body.strip() and not any(v.startswith('## ') for v in body.splitlines()):findings.append({'code':'headings','message':'본문의 소제목 구성을 확인하세요.'})
    if len(lines)!=len(set(lines)):findings.append({'code':'repeated_paragraph','message':'같은 긴 문단이 반복됩니다.'})
    if not any(s.get('status')=='collected' for s in document.get('sources',[])):findings.append({'code':'references','message':'수집된 참고 자료가 없습니다.'})
    if document.get('unverifiedClaims'):findings.append({'code':'claims','message':'검증 대기 주장을 직접 확인하세요.'})
    return {'method':'editorial_rules','factsVerified':False,'rankingGuaranteed':False,
            'charactersWithoutWhitespace':len(''.join(body.split())),'findings':findings,
            'note':'형식·반복 검사입니다. 사실·출처·원본성은 사람이 별도로 검토합니다.'}
