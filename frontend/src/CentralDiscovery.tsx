import { useEffect, useState } from 'react'

type Result = { id: string; url: string; blogOrigin: string; title: string; section: string; sectionPosition: number | null; platform: string; evidence: string }
type Engine = { engine: string; status: string; targetPresence: string; checkedAt?: string; results: Result[] }
type Run = { id: string; keyword: string; createdAt: string; status: string; engines: Record<string, Engine> }
type Props = { api: (path: string, method?: string, body?: unknown) => Promise<any> }
const kinds: Record<string, string> = { tistory: '티스토리', wordpress: '워드프레스', unknown: '유형 미확인' }
function safeLink(url: string) { try { return ['https:', 'http:'].includes(new URL(url).protocol) } catch { return false } }

export default function CentralDiscovery({ api }: Props) {
  const [keyword, setKeyword] = useState('카카오택시 분실물 조회')
  const [runs, setRuns] = useState<Run[]>([])
  const [configured, setConfigured] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('검색 연결 상태를 확인하고 있습니다.')
  async function load() {
    const value = await api('discovery')
    if (!Array.isArray(value.runs) || typeof value.configured !== 'boolean') throw new Error('검색 기록을 확인하지 못했습니다.')
    setRuns(value.runs); setConfigured(value.configured)
    setMessage(value.configured ? '검색 API 연결 설정 있음 · 실제 결과 검증은 별도입니다.' : '검색 API 미연결 · 서버에 연결 키를 설정해야 실제 검색할 수 있습니다.')
  }
  useEffect(() => { let active = true; api('discovery').then(value => { if (active && Array.isArray(value.runs)) { setRuns(value.runs); setConfigured(value.configured === true); setMessage(value.configured ? '검색 요청 준비' : '검색 API 미연결 · 실제 검색은 아직 실행할 수 없습니다.') } }).catch(() => { if (active) setMessage('검색 기록 조회 실패 · 다시 불러오세요.') }); return () => { active = false } }, [api])
  async function perform(action: () => Promise<void>) { if (busy) return; setBusy(true); try { await action() } catch (e) { setMessage(e instanceof Error ? e.message : '확인 실패') } finally { setBusy(false) } }
  function replace(run: Run) { setRuns(old => [run, ...old.filter(r => r.id !== run.id)]) }
  return <section className="panel"><h2>키워드 발굴 · 실제 검색 연결</h2><p>네이버·구글 첫 페이지를 각각 수집합니다. 검색량 조건과 최종 선별은 아직 적용하지 않습니다.</p>
    <p role="status">{message}</p>
    <form className="keyword-form" onSubmit={event => { event.preventDefault(); void perform(async () => { setMessage('양쪽 검색 요청 중 · 완료 전 창을 닫지 마세요.'); const value = await api('discovery', 'POST', { keyword }); replace(value); setMessage(value.status === 'retrieved' ? '양쪽 검색 결과 수신 · 사이트 유형과 수집 범위를 확인하세요. 최종 선별 전입니다.' : '확인 미완료 · 실패를 노출 없음으로 처리하지 않았습니다.') }) }}>
      <input aria-label="발굴 시작 키워드" value={keyword} maxLength={200} onChange={e => setKeyword(e.target.value)} disabled={busy} />
      <button type="submit" disabled={!configured || busy || !keyword.trim()}>네이버·구글 첫 페이지 검색</button>
      <button type="button" disabled={busy} onClick={() => void perform(load)}>검색 기록 다시 불러오기</button>
    </form>
    <p>검색 1회당 양쪽 API를 각 1회 요청합니다. 자동 재시도·2페이지 검색은 하지 않습니다. 실제 화면과의 일치 검증이 필요하며, 일부 영역이나 유형이 미확인이면 ‘없음’으로 단정하지 않습니다.</p>
    {runs.map(run => <article key={run.id} className="panel"><h3>{run.keyword}</h3><p>검색 기록 ID: {run.id}</p><p>{run.status === 'retrieved' ? '양쪽 결과 수신 · 최종 검증 전' : '검증 미완료'} · {new Date(run.createdAt).toLocaleString('ko-KR')}</p>
      {['naver', 'google'].map(name => { const engine = run.engines[name]; return <div key={name}><h4>{name === 'naver' ? '네이버' : '구글'} · {engine.status === 'retrieved' ? '결과 수신' : '미확인'} · {engine.targetPresence === 'present' ? '대상 유형 발견' : '노출 여부 미확인'}</h4>
        <p>인식 가능한 검색 영역만 수집 · 광고 및 네이버 블로그 제외 · 순위는 해당 영역 내 번호</p>
        {engine.results.map(row => <div className="keyword-item" key={row.id}><div><strong>{row.title}</strong><p>{kinds[row.platform] || '유형 미확인'} · {row.section} · 영역 내 {row.sectionPosition ?? '미기록'}</p>{safeLink(row.url) && <a href={row.url} target="_blank" rel="noopener noreferrer">{row.url}</a>}<p>블로그 기준 주소: {row.blogOrigin} · 근거: {row.evidence}</p></div>
          {['tistory', 'wordpress'].includes(row.platform) && <button disabled={busy || run.status !== 'retrieved'} onClick={() => void perform(async () => { const value = await api('feed-collections/from-discovery', 'POST', { runId: run.id, resultId: row.id }); setMessage(value.status === 'collected' ? 'RSS를 수집했습니다. RSS 수집 기록 불러오기로 후보를 확인하세요.' : 'RSS 수집 미완료 · 수집 기록에서 이유를 확인하세요.') })}>이 블로그 RSS 수집</button>}
          {row.platform !== 'tistory' && <button disabled={busy} onClick={() => void perform(async () => { replace(await api(`discovery/${run.id}/results/${row.id}/inspect`, 'POST')); setMessage('사이트 유형 확인 결과를 저장했습니다. 미확인은 워드프레스가 아니라는 뜻이 아닙니다.') })}>워드프레스 여부 확인</button>}
        </div>)}
      </div> })}
    </article>)}
  </section>
}
