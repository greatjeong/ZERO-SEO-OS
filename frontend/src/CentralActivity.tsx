import { useState } from 'react'
type Item = { id: string; source: string; sourceId: string; stage: number; at: string; title: string; label: string; state: string; message: string; target: 'discovery' | 'feeds' | 'bank' }
type Activity = { checkedAt: string; scope: string; hasEarlierRecords: boolean; incompleteSources: string[]; counts: { records: number; attention: number; review: number }; items: Item[] }
type Props = { api: (path: string, method?: string, body?: unknown) => Promise<any>; onOpen: (target: Item['target'], title: string) => void }
const sources: Record<string, string> = { search: '검색', rss: 'RSS 수집', keyword: '키워드·작성 준비' }
export default function CentralActivity({ api, onOpen }: Props) {
  const [data, setData] = useState<Activity | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('진행 기록을 아직 조회하지 않았습니다.')
  const [source, setSource] = useState('all')
  const [state, setState] = useState('all')
  async function load() {
    if (busy) return
    setBusy(true)
    try { const value = await api('activity'); if (!Array.isArray(value.items) || !value.counts || !Array.isArray(value.incompleteSources)) throw new Error('진행 기록 응답 형식 미확인'); setData(value); setMessage(value.incompleteSources.length ? '일부 기록을 읽지 못했습니다. 표시된 건수는 전체 결과가 아닙니다.' : '저장된 진행 기록을 불러왔습니다. 새 작업을 실행하지 않았습니다.') }
    catch (e) { setMessage(e instanceof Error ? e.message : '조회 실패 · 이전 기록은 유지됩니다.') }
    finally { setBusy(false) }
  }
  const items = data?.items.filter(item => (source === 'all' || item.source === source) && (state === 'all' || item.state === state)) || []
  return <section className="panel central-activity"><div className="central-card-heading"><div><span className="central-overline">ACTIVITY</span><h2>진행 기록·확인 상태</h2></div><button disabled={busy} onClick={() => void load()}>{busy ? '진행 기록 조회 중…' : '진행 기록 불러오기'}</button></div>
    <p role="status">{message}</p>
    {data && <><p>조회 시각: {new Date(data.checkedAt).toLocaleString('ko-KR')} · 검색·RSS·키워드별 최근 20개 기록</p><div className="central-activity-counts"><span>조회 기록 <b>{data.counts.records}</b></span><span>확인 필요 기록 <b>{data.counts.attention}</b></span><span>검토 대기 기록 <b>{data.counts.review}</b></span></div>{data.incompleteSources.length > 0 && <p>미확인 영역: {data.incompleteSources.map(v => sources[v] || v).join(', ')}</p>}{data.hasEarlierRecords && <p>이전 기록이 더 있습니다. 해당 단계에서 개별 기록을 확인하세요.</p>}
    <div className="central-activity-filters"><label>기록 종류<select aria-label="진행 기록 종류" value={source} onChange={e => setSource(e.target.value)}><option value="all">전체</option><option value="search">검색</option><option value="rss">RSS 수집</option><option value="keyword">키워드·작성 준비</option></select></label><label>기록 상태<select aria-label="진행 기록 상태" value={state} onChange={e => setState(e.target.value)}><option value="all">전체 상태</option><option value="attention">확인 필요</option><option value="review">검토 대기</option><option value="recorded">기록됨</option></select></label></div>
    {items.map(item => <article key={item.id} className={`central-activity-row ${item.state}`}><div><span className="central-activity-meta">{sources[item.source]} · STEP 0{item.stage} · {new Date(item.at).toLocaleString('ko-KR')}</span><h3>{item.title}</h3><strong>{item.label}</strong><p>{item.message}</p></div><button onClick={() => onOpen(item.target, item.title)}>해당 단계 열기</button></article>)}
    {!items.length && <div className="central-empty">표시할 기록이 없습니다.</div>}</>}
    <p>기록 조회나 단계 이동으로 검색·수집·글 작성을 재실행하지 않습니다. 표시는 기록 당시 상태이며 현재 미해결 오류 수가 아닙니다. 과거 기록의 성공은 현재 연결 상태나 글 발행 성공을 뜻하지 않습니다.</p>
  </section>
}
