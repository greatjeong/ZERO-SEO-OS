import { useState } from 'react'
type Match = { engine: string; url: string; title?: string; platform: string; section?: string; sectionPosition?: number | null }
export type Selection = { eligible: boolean; tier: number | null; naverMonthly: number | null; reasons: string[]; matches: Match[] }
type Row = { id: string; keyword: string; revision: number; selection?: Selection; searchVolume?: { naver?: { monthly: number | null; source: string; checkedAt: string; method?: string }; google?: { monthly: number | null } } | null; evidence?: { engines: Record<string, { checkedAt?: string; status: string }> } | null }
export default function KeywordRulePanel({ row, api, disabled, onUpdate }: { row: Row; api: (path: string, method?: string, body?: unknown) => Promise<any>; disabled?: boolean; onUpdate: (value: any) => void | Promise<void> }) {
  const [naver, setNaver] = useState(''), [google, setGoogle] = useState(''), [source, setSource] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState('')
  const rule=row.selection
  const parse=(v:string)=>{if(!v.trim())return null;const n=Number(v);if(!/^\d+$/.test(v)||!Number.isSafeInteger(n))throw Error('검색량은 0 이상의 정수로 입력하세요. 빈칸은 미확인입니다.');return n}
  return <section className="keyword-rule-panel" aria-label={`${row.keyword} 선별 조건`}>
    <p><strong>{rule?.eligible?'사용 가능':'사용 목록 제외'}</strong> · {rule?.tier?`${rule.tier}단계`:'검색량 구간 미확정'} · 네이버 월간 {rule?.naverMonthly == null?'미확인':rule.naverMonthly.toLocaleString()+'회'}</p>
    <p>1단계 500~2,999 · 2단계 3,000~9,999 · 3단계 10,000 이상. 구글 검색량은 참고용입니다.</p>
    {!!rule?.reasons.length && <ul>{rule.reasons.map(r=><li key={r}>{r}</li>)}</ul>}
    <details><summary>검색량 확인값 입력 · 자동 조회 미연결</summary><p>직접 확인한 월간 검색량과 출처를 기록합니다. 자동 수집값으로 표시하지 않습니다. 미확인인 경우 빈칸으로 기록하면 사용 목록에서 제외됩니다.</p>
      <label>네이버 월간 검색량<input aria-label={`${row.keyword} 네이버 월간 검색량`} type="number" min="0" step="1" value={naver} onChange={e=>setNaver(e.target.value)} placeholder="빈칸 = 미확인" /></label>
      <label>구글 월간 검색량 · 참고<input aria-label={`${row.keyword} 구글 월간 검색량`} type="number" min="0" step="1" value={google} onChange={e=>setGoogle(e.target.value)} placeholder="빈칸 = 미확인" /></label>
      <label>확인 출처<input aria-label={`${row.keyword} 검색량 출처`} maxLength={500} value={source} onChange={e=>setSource(e.target.value)} placeholder="확인한 도구·자료·측정 기간" /></label>
      <button disabled={disabled||busy||!source.trim()} onClick={()=>void (async()=>{setBusy(true);try{const value=await api(`keyword-bank/${row.id}/volume`,'POST',{revision:row.revision,naverMonthly:parse(naver),googleMonthly:parse(google),source:source.trim()});await onUpdate(value);setMessage(value.selection?.eligible?'조건 통과 · 사용 DB에 반영했습니다.':'사용 목록에서 제외했습니다. 사유와 원본은 보관합니다.')}catch(e){setMessage(e instanceof Error?e.message:'기록 실패')}finally{setBusy(false)}})()}>검색량 기록·조건 적용</button>
      <p role="status">{message}</p>
    </details>
    {row.searchVolume?.naver && <p>검색량 출처: {row.searchVolume.naver.source} · {new Date(row.searchVolume.naver.checkedAt).toLocaleString('ko-KR')} · {row.searchVolume.naver.method==='preview_fixture'?'시뮬레이션 수치':'수동 확인 기록'}</p>}
    <div className="keyword-evidence-links">{(['naver','google'] as const).map(engine=><p key={engine}><strong>{engine==='naver'?'네이버':'구글'}</strong> · {row.evidence?.engines[engine]?.status==='retrieved'?'조회 기록 있음':'미확인'} · <a target="_blank" rel="noopener noreferrer" href={engine==='naver'?`https://search.naver.com/search.naver?query=${encodeURIComponent(row.keyword)}`:`https://www.google.com/search?q=${encodeURIComponent(row.keyword)}`}>검색 결과 열기</a></p>)}</div>
    {rule?.matches.map((m,i)=><div key={`${m.engine}:${m.url}:${i}`}><strong>{m.engine==='naver'?'네이버':'구글'} · {m.platform==='tistory'?'티스토리':'워드프레스'}</strong><p>{m.title||'제목 미확인'} · {m.section||'결과 영역 미확인'} · 위치 {m.sectionPosition??'미확인'}</p><a target="_blank" rel="noopener noreferrer" href={m.url}>원문 확인</a><p>{m.url} · 확인 시각 {row.evidence?.engines[m.engine]?.checkedAt||'미확인'}</p></div>)}
  </section>
}
