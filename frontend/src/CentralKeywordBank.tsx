import { useState } from 'react'
type SearchResult = { id: string; platform: string; url: string; title: string }
type Evidence = { id: string; engines: Record<string, { status: string; targetPresence: string; results: SearchResult[] }> }
type Keyword = { id: string; keyword: string; revision: number; status: string; createdAt: string; checkedAt: string | null; nextCheckAt: string | null; retryAt: string | null; reviewRequired: boolean; verification: string; latestRunId: string | null; sources: unknown[]; evidence: Evidence | null }
type Preparation = { id: string; keyword: string; slot: string; siteUrl: string; eligible: boolean; articleGenerated: boolean }
type Props = { api: (path: string, method?: string, body?: unknown) => Promise<any> }
const date = (v: string | null) => v ? new Date(v).toLocaleString('ko-KR') : '미확인'
const labels: Record<string, string> = { pending: '검토 대기', active: '활성', excluded: '활성 제외' }
export default function CentralKeywordBank({ api }: Props) {
  const [rows, setRows] = useState<Keyword[]>([])
  const [queue, setQueue] = useState<Preparation[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('RSS 후보를 검토 대기로 보낸 뒤 목록을 불러오세요.')
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [runIds, setRunIds] = useState<Record<string, string>>({})
  const [slots, setSlots] = useState<Record<string, string>>({})
  const [history, setHistory] = useState<Record<string, { event: string; at: string; detail: unknown }[]>>({})
  const replace = (row: Keyword) => setRows(old => old.map(r => r.id === row.id ? row : r))
  async function work(action: () => Promise<void>) { if (busy) return; setBusy(true); try { await action() } catch (e) { setMessage(e instanceof Error ? e.message : '처리 결과 미확인 · 새로 불러오세요.') } finally { setBusy(false) } }
  async function load(offset = 0) { const value = await api(`keyword-bank?offset=${offset}`); if (!Array.isArray(value.keywords)) throw new Error('DB 형식을 확인하지 못했습니다.'); setRows(old => offset === 0 ? value.keywords : [...old, ...value.keywords.filter((r: Keyword) => !old.some(v => v.id === r.id))]); setNext(value.nextOffset); const jobs = await api('article-preparations'); setQueue(jobs.preparations); setMessage('서버의 키워드·원본 글 작성 준비 기록을 불러왔습니다.') }
  async function review(row: Keyword, decision: string) { replace(await api(`keyword-bank/${row.id}/review`, 'POST', { revision: row.revision, runId: row.latestRunId, decision, reason: reasons[row.id] || '' })); setMessage(decision === 'active' ? '활성 DB에 반영했습니다. 검색량 조건은 적용하지 않았습니다.' : '활성 목록에서 제외했습니다. 원본·출처·이력은 보존됩니다.'); const jobs = await api('article-preparations'); setQueue(jobs.preparations) }
  const visible = rows.filter(r => (filter === 'all' || r.status === filter) && r.keyword.includes(query))
  return <>
    <section className="panel"><h2>키워드 선별 · 누적 DB · 월간 재검증</h2><p>4~5단계 · 양쪽 검색 결과를 확인한 뒤 직접 선택합니다. 검색량은 미측정이며 수치 조건은 추후 설정합니다.</p><p role="status">{message}</p>
      <div className="backup-actions"><button disabled={busy} onClick={() => void work(() => load())}>키워드 DB·작성 준비 불러오기</button><button disabled={busy} onClick={() => void work(async () => { const value = await api('keyword-bank/export'); const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = 'zero-keyword-bank.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); setMessage('키워드·출처·검토 이력·작성 준비 전체 내보내기를 요청했습니다.') })}>키워드 DB 전체 JSON 내려받기</button></div>
      <p>다음 달 같은 날짜를 정기 검사 예정일로 계산합니다. 정기 실행 프로그램은 준비 중인 서버에 연결한 뒤 작동합니다. 조회 실패는 기존 활성 상태를 유지하고 재확인 대상으로 남깁니다.</p>
      <label>불러온 키워드 검색<input aria-label="키워드 DB 검색" value={query} onChange={e => setQuery(e.target.value)} /></label><label>상태<select aria-label="키워드 DB 상태" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">전체</option><option value="pending">검토 대기</option><option value="active">활성</option><option value="excluded">활성 제외</option></select></label>
      {visible.map(row => <article key={row.id} className="panel"><h3>{row.keyword} · {labels[row.status]}</h3><p>출처 {row.sources.length}건 · 버전 {row.revision} · 검색량 미측정</p><p>최초 축적 {date(row.createdAt)} / 최근 양쪽 확인 {date(row.checkedAt)}</p><p>정기 검사 예정 {date(row.nextCheckAt)} / 재확인 예정 {date(row.retryAt)}</p><p>{row.verification === 'both_retrieved' ? '양쪽 결과 수신' : '양쪽 검색 확인 미완료'} · {row.reviewRequired ? '추가 검토 필요' : '대상 유형 확인'}</p>
        <div className="backup-actions"><button disabled={busy} onClick={() => void work(async () => { replace(await api(`keyword-bank/${row.id}/check`, 'POST', { revision: row.revision })); setMessage('최신 검색 결과를 기록했습니다. 활성 상태와 확인 미완료 상태를 구분해서 확인하세요.') })}>네이버·구글 검색·재검증</button><button disabled={busy} onClick={() => void work(async () => { const value = await api(`keyword-bank/${row.id}/history`); setHistory(old => ({ ...old, [row.id]: value.events })) })}>변경 이력 보기</button></div>
        <label>기존 검색 기록 ID 연결<input aria-label={`${row.keyword} 검색 기록 ID`} value={runIds[row.id] || ''} onChange={e => setRunIds(old => ({ ...old, [row.id]: e.target.value }))} /></label><button disabled={busy || !runIds[row.id]} onClick={() => void work(async () => { replace(await api(`keyword-bank/${row.id}/evidence`, 'POST', { revision: row.revision, runId: runIds[row.id] })); setMessage('일치하는 키워드의 검색 기록을 연결했습니다.') })}>기존 검색 근거 연결</button>
        {row.evidence && <div><p>최신 검색 ID: {row.latestRunId}</p>{Object.entries(row.evidence.engines).map(([engine, evidence]) => <div key={engine}><h4>{engine === 'naver' ? '네이버' : '구글'} · {evidence.status === 'retrieved' ? '수신' : '미확인'} · {evidence.targetPresence === 'present' ? '대상 유형 있음' : '유형 미확인'}</h4>{evidence.results.map(result => <div key={result.id}><span>{result.title} · {result.platform}</span>{/^https?:\/\//.test(result.url) && <a href={result.url} target="_blank" rel="noopener noreferrer">원문</a>}{result.platform === 'unknown' && <button disabled={busy} onClick={() => void work(async () => { await api(`discovery/${row.latestRunId}/results/${result.id}/inspect`, 'POST'); replace(await api(`keyword-bank/${row.id}/evidence`, 'POST', { revision: row.revision, runId: row.latestRunId })); setMessage('페이지의 유형 확인 근거를 갱신했습니다.') })}>워드프레스 유형 확인</button>}</div>)}</div>)}</div>}
        <label>검토 이유<input aria-label={`${row.keyword} 검토 이유`} value={reasons[row.id] || ''} maxLength={500} onChange={e => setReasons(old => ({ ...old, [row.id]: e.target.value }))} /></label>
        <div className="backup-actions"><button disabled={busy || row.verification !== 'both_retrieved' || row.reviewRequired || !reasons[row.id]?.trim()} onClick={() => void work(() => review(row, 'active'))}>선택·활성 DB 반영</button><button disabled={busy || row.verification !== 'both_retrieved' || !reasons[row.id]?.trim()} onClick={() => void work(() => review(row, 'excluded'))}>활성 제외·원본 보존</button></div>
        <label>원본 글 대상<select aria-label={`${row.keyword} 작성 대상`} value={slots[row.id] || 'A-1'} onChange={e => setSlots(old => ({ ...old, [row.id]: e.target.value }))}><option>A-1</option><option>A-2</option></select></label><button disabled={busy || row.status !== 'active' || row.verification !== 'both_retrieved' || row.reviewRequired} onClick={() => void work(async () => { const value = await api(`keyword-bank/${row.id}/handoff`, 'POST', { revision: row.revision, slot: slots[row.id] || 'A-1' }); setMessage(value.created ? '통합 관리의 원본 글 작성 준비에 연결했습니다. 키워드 원본은 유지됩니다.' : '같은 사이트에 이미 연결된 키워드입니다. 중복 작업을 만들지 않았습니다.'); setQueue((await api('article-preparations')).preparations) })}>통합 관리로 연결</button>
        {history[row.id]?.map((event, i) => <p key={i}>{date(event.at)} · {event.event} · {JSON.stringify(event.detail)}</p>)}
      </article>)}
      {!visible.length && <p>불러온 목록에 해당하는 키워드가 없습니다.</p>}{next !== null && <button disabled={busy} onClick={() => void work(() => load(next))}>다음 100개 불러오기</button>}
    </section>
    <section className="panel"><h2>통합 관리 · 원본 글 작성 준비</h2><p>6단계 · 선택한 키워드와 대상 사이트를 연결합니다. 실제 AI 글 생성·워드프레스 저장·발행은 이 단계에 포함하지 않습니다.</p>{!queue.length && <p>연결된 키워드가 없습니다. 위에서 기록을 불러오거나 활성 키워드를 연결하세요.</p>}{queue.map(job => <div className="keyword-item" key={job.id}><strong>{job.keyword}</strong><span>{job.slot} · {job.siteUrl}</span><span>{job.eligible ? '원본 글 작성 준비' : '재검증·대상 사이트 확인 필요'}</span></div>)}</section>
  </>
}
