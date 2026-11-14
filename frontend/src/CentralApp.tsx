import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import './central.css'
import CentralKeywordBank from './CentralKeywordBank'
import CentralFeeds from './CentralFeeds'
import CentralDiscovery from './CentralDiscovery'
import CentralWordPress from './CentralWordPress'
import CentralDraftHistory from './CentralDraftHistory'
import CentralDraftSave from './CentralDraftSave'

type Slot = 'A-1' | 'A-2'
type Job = { id: string; site: Slot; keyword: string; status: string; createdAt: string }
type Data = { format: 'zero-seo-os-backup'; version: 2; exportedAt: string; sites: Record<Slot, { name: string; url: string }>; keywordsBySite: Record<Slot, string[]>; jobs: Job[] }
type Workspace = { revision: number; data: Data | null }
const emptyData = (): Data => ({ format: 'zero-seo-os-backup', version: 2, exportedAt: new Date().toISOString(), sites: { 'A-1': { name: '', url: '' }, 'A-2': { name: '', url: '' } }, keywordsBySite: { 'A-1': [], 'A-2': [] }, jobs: [] })
function checkedWorkspace(value: Workspace): Workspace {
  if (!value || !Number.isSafeInteger(value.revision) || value.revision < 0 || (value.data !== null && (value.data.format !== 'zero-seo-os-backup' || value.data.version !== 2 || !value.data.sites || !value.data.keywordsBySite || !Array.isArray(value.data.jobs)))) throw new Error('서버 데이터 형식을 확인하지 못했습니다.')
  if (value.data) {
    const data = value.data
    if (typeof data.exportedAt !== 'string' || !(['A-1', 'A-2'] as const).every(slot => typeof data.sites[slot]?.name === 'string' && typeof data.sites[slot]?.url === 'string' && Array.isArray(data.keywordsBySite[slot]) && data.keywordsBySite[slot].every(item => typeof item === 'string')) || !data.jobs.every(job => job && typeof job.id === 'string' && (job.site === 'A-1' || job.site === 'A-2') && typeof job.keyword === 'string' && typeof job.status === 'string' && typeof job.createdAt === 'string')) throw new Error('서버 데이터 형식을 확인하지 못했습니다.')
  }
  return value
}
function newJob(site: Slot, keyword: string): Job { return { id: crypto.randomUUID(), site, keyword, status: '대기', createdAt: new Date().toISOString() } }

export default function CentralApp() {
  const [phase, setPhase] = useState<'checking' | 'login' | 'ready'>('checking')
  const [password, setPassword] = useState('')
  const [workspace, setWorkspace] = useState<Workspace>({ revision: 0, data: null })
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [site, setSite] = useState<Slot>('A-1')
  const [keyword, setKeyword] = useState('')
  const [snapshots, setSnapshots] = useState<{ revision: number; created_at: string }[]>([])
  const csrf = useRef<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const api = useCallback(async (path: string, method = 'GET', body?: unknown) => {
    const headers: Record<string, string> = {}
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (method !== 'GET' && csrf.current) headers['X-CSRF-Token'] = csrf.current
    const response = await fetch(`/api/${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(method === 'POST' ? 45000 : 20000) })
    let result
    try { result = await response.json() } catch { throw new Error('서버 응답 형식을 확인하지 못했습니다.') }
    if (!response.ok) throw new Error(typeof result.message === 'string' ? result.message : '요청 결과를 확인하지 못했습니다.')
    return result
  }, [])

  useEffect(() => {
    let active = true
    async function open() {
      try {
        const session = await api('session')
        if (session.authenticated !== true || typeof session.csrf !== 'string') throw new Error('로그인이 필요합니다.')
        const loaded = checkedWorkspace(await api('workspace'))
        if (active) { csrf.current = session.csrf; setWorkspace(loaded); setPhase('ready') }
      } catch { if (active) setPhase('login') }
    }
    void open()
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  async function login() {
    setBusy(true); setMessage('')
    try {
      const result = await api('login', 'POST', { password })
      if (result.authenticated !== true || typeof result.csrf !== 'string') throw new Error('로그인을 확인하지 못했습니다.')
      csrf.current = result.csrf
      if (!dirty) setWorkspace(checkedWorkspace(await api('workspace')))
      setPhase('ready')
      if (dirty) setMessage('작성 중인 변경을 유지했습니다. 서버 저장으로 충돌 여부를 확인하세요.')
    } catch (error) { setMessage(error instanceof Error ? error.message : '로그인 실패') }
    finally { setPassword(''); setBusy(false) }
  }

  function changeData(next: Data) { setWorkspace(prev => ({ ...prev, data: next })); setDirty(true); setMessage('변경 사항이 있습니다. 서버 저장을 눌러주세요.') }
  async function persist(data: Data, baseRevision = workspace.revision) {
    const result = checkedWorkspace(await api('workspace', 'PUT', { baseRevision, data: { ...data, exportedAt: new Date().toISOString() } }))
    if (result.revision !== baseRevision + 1 || !result.data) throw new Error('저장 결과 미확인 · 다시 저장하기 전에 서버 데이터를 확인하세요.')
    setWorkspace(result); setDirty(false)
    setMessage(`서버 저장 확인 · 버전 ${result.revision}. 이전 저장본은 유지됩니다.`)
  }
  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : '요청 실패 · 현재 변경은 유지됩니다.') }
    finally { setBusy(false) }
  }
  async function reload() {
    if (dirty && !window.confirm('저장 전 변경을 버리고 서버 데이터를 다시 불러올까요? 필요한 데이터는 먼저 JSON으로 내려받으세요.')) return
    setWorkspace(checkedWorkspace(await api('workspace'))); setDirty(false); setMessage('서버 데이터를 다시 불러왔습니다.')
  }
  function exportBackup() {
    if (!workspace.data) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(workspace.data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `zero-central-${new Date().toISOString().slice(0, 10)}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setMessage('JSON 다운로드를 요청했습니다. 다운로드 폴더를 확인하세요. 초안 DB와 인증정보는 포함되지 않습니다.')
  }
  async function importFile(file?: File) {
    if (!file) return
    await run(async () => {
      if (file.size > 5 * 1024 * 1024) throw new Error('백업 파일은 5MB 이하여야 합니다.')
      let parsed: unknown
      try { parsed = JSON.parse(await file.text()) } catch { throw new Error('JSON 백업 형식이 올바르지 않습니다.') }
      const preview = await api('import/preview', 'POST', parsed)
      if (!preview.data || !Number.isSafeInteger(preview.baseRevision) || !preview.counts) throw new Error('가져오기 미리보기 형식 오류')
      if (!window.confirm(`A-1 ${preview.counts['A-1']}개 / A-2 ${preview.counts['A-2']}개 / 작업 ${preview.jobs}개로 서버 버전 ${preview.baseRevision}을 교체합니다. 저장 전 화면 변경도 교체됩니다. 이전 서버 저장본은 유지합니다. 계속할까요?`)) return
      await persist(preview.data, preview.baseRevision)
    })
    if (fileInput.current) fileInput.current.value = ''
  }

  const data = workspace.data
  const jobs = data?.jobs.filter(job => job.site === site) || []
  const keywords = data?.keywordsBySite[site] || []
  function addKeyword() {
    if (!data || !keyword.trim()) return
    const value = keyword.trim()
    if (keywords.some(v => v.toLowerCase() === value.toLowerCase())) { setMessage('이미 등록된 키워드입니다.'); return }
    changeData({ ...data, keywordsBySite: { ...data.keywordsBySite, [site]: [...keywords, value] } }); setKeyword('')
  }
  function enqueue(value: string) {
    if (!data) return
    if (jobs.some(j => j.keyword.toLowerCase() === value.toLowerCase() && j.status === '대기')) { setMessage('동일 키워드의 대기 작업이 있습니다.'); return }
    changeData({ ...data, jobs: [newJob(site, value), ...data.jobs] })
  }

  return <main className="central-shell">
    <header className="panel-heading"><div><h1>ZERO SEO OS</h1><p>본인용 비공개 중앙 작업 공간</p></div><span className="tag">중앙 버전 개발 중</span></header>
    {message && <p role="status" className="global-message">{message}</p>}
    {phase === 'checking' && <p role="status">로그인 상태 확인 중…</p>}
    {phase === 'login' && <section className="panel central-login"><h2>본인 로그인</h2><form onSubmit={event => { event.preventDefault(); void login() }}><label>서비스 비밀번호<input type="password" autoComplete="current-password" value={password} disabled={busy} onChange={event => setPassword(event.target.value)} required /></label><button disabled={busy} type="submit">로그인</button></form><p>워드프레스 앱 비밀번호가 아닌, 이 서비스의 본인 로그인 비밀번호입니다.</p></section>}
    {phase === 'ready' && <>
      <section className="panel"><div className="backup-actions">
        <strong>{dirty ? '저장 전 변경 있음' : `서버 기준 버전 ${workspace.revision}`}</strong>
        <button disabled={busy || !data || !dirty} onClick={() => void run(async () => { if (data) await persist(data) })}>변경 사항 서버 저장</button>
        <button disabled={busy} onClick={() => void run(reload)}>서버 데이터 다시 불러오기</button>
        <button disabled={busy} onClick={() => { setPassword(''); setPhase('login'); setMessage('서비스 비밀번호로 다시 로그인하세요. 작성 중인 변경은 유지됩니다.') }}>로그인 갱신</button>
        <button disabled={busy} onClick={() => void run(async () => { if (dirty && !window.confirm('저장 전 변경을 버리고 로그아웃할까요?')) return; await api('logout', 'POST'); csrf.current = null; setWorkspace({ revision: 0, data: null }); setDirty(false); setSnapshots([]); setPhase('login'); setMessage('로그아웃했습니다.') })}>로그아웃</button>
      </div><p>다른 PC에서는 서버에 저장한 버전을 불러옵니다. 브라우저 로컬 데이터는 자동으로 가져오거나 지우지 않습니다.</p></section>
      <CentralDiscovery api={api} />
      <CentralFeeds api={api} />
      <CentralKeywordBank api={api} />
      {!data && <section className="panel"><h2>서버 작업 공간이 비어 있습니다</h2><p>기존 데이터가 있으면 아래 JSON 가져오기를 먼저 이용하세요.</p><button disabled={busy} onClick={() => void run(async () => { if (window.confirm('기존 브라우저 데이터는 그대로 두고 빈 서버 작업 공간을 만들까요?')) await persist(emptyData()) })}>빈 작업 공간으로 시작</button></section>}
      {data && <fieldset className="central-fields" disabled={busy}>
        <div className="site-switch">{(['A-1', 'A-2'] as const).map(slot => <button className={site === slot ? 'selected' : ''} key={slot} onClick={() => { setSite(slot); setKeyword('') }}>{slot} 사이트</button>)}</div>
        <section className="panel"><h2>{site} 사이트 정보</h2><div className="wp-fields"><label>사이트 이름<input value={data.sites[site].name} maxLength={100} onChange={event => changeData({ ...data, sites: { ...data.sites, [site]: { ...data.sites[site], name: event.target.value } } })} /></label><label>워드프레스 주소<input type="url" value={data.sites[site].url} placeholder="https://example.com" onChange={event => changeData({ ...data, sites: { ...data.sites, [site]: { ...data.sites[site], url: event.target.value } } })} /></label></div><CentralWordPress key={`${site}:${data.sites[site].url}:${workspace.revision}`} slot={site} url={data.sites[site].url} disabled={busy || dirty} api={api} /></section>
        <section className="panel"><CentralDraftHistory key={`${site}:${data.sites[site].url}:${workspace.revision}`} slot={site} url={data.sites[site].url} disabled={busy || dirty} api={api} /></section>
        <section className="panel"><CentralDraftSave key={`${site}:${data.sites[site].url}:${workspace.revision}`} slot={site} url={data.sites[site].url} disabled={busy || dirty} api={api} /></section>
        <section className="panel"><h2>키워드 관리</h2><form className="keyword-form" onSubmit={event => { event.preventDefault(); addKeyword() }}><input aria-label="등록할 키워드" value={keyword} onChange={event => setKeyword(event.target.value)} /><button type="submit">키워드 등록</button></form>
          {!keywords.length && <p>등록된 키워드가 없습니다.</p>}{keywords.map(value => <div key={value} className="keyword-item"><strong>{value}</strong><button onClick={() => enqueue(value)}>작업 등록</button><button onClick={() => { if (window.confirm('키워드를 삭제할까요? 기존 작업 기록은 유지됩니다.')) changeData({ ...data, keywordsBySite: { ...data.keywordsBySite, [site]: keywords.filter(v => v !== value) } }) }}>삭제</button></div>)}
        </section>
        <section className="panel"><h2>작업 기록</h2><p>작업은 등록만 하며 AI 생성이나 발행은 실행되지 않습니다.</p>{!jobs.length && <p>등록된 작업이 없습니다.</p>}{jobs.map(job => <div className="job-item" key={job.id}><strong>{job.keyword}</strong><span>{job.status}</span>{job.status === '대기' && <button onClick={() => changeData({ ...data, jobs: data.jobs.map(j => j.id === job.id ? { ...j, status: '취소' } : j) })}>취소</button>}{job.status === '취소' && <button onClick={() => { if (jobs.some(j => j.id !== job.id && j.status === '대기' && j.keyword.toLowerCase() === job.keyword.toLowerCase())) { setMessage('동일 키워드의 대기 작업이 있습니다.'); return }; changeData({ ...data, jobs: data.jobs.map(j => j.id === job.id ? { ...j, status: '대기' } : j) }) }}>다시 대기</button>}</div>)}</section>
      </fieldset>}
      <section className="panel"><h2>데이터 백업·가져오기</h2><div className="backup-actions"><button disabled={!data || busy} onClick={exportBackup}>현재 데이터 JSON 다운로드</button><label>v1/v2 JSON 가져오기<input ref={fileInput} type="file" accept=".json,application/json" disabled={busy} onChange={event => void importFile(event.target.files?.[0])} /></label><button disabled={busy} onClick={() => void run(async () => { const result = await api('snapshots'); if (!Array.isArray(result.snapshots)) throw new Error('저장본 목록 형식 오류'); setSnapshots(result.snapshots); setMessage(`저장본 ${result.snapshots.length}개 조회`) })}>이전 저장본 조회</button></div>
        <p>v1은 사이트 이름·주소를 유지하고 키워드·작업을 가져옵니다. v2는 사이트 정보도 가져옵니다. 초안 중복 방지 DB와 인증정보는 포함되지 않습니다.</p>
        {snapshots.map(snapshot => <button disabled={busy} key={snapshot.revision} onClick={() => void run(async () => { if (!window.confirm(`저장본 ${snapshot.revision}의 내용으로 새 버전을 만들까요? 저장 전 변경은 교체되며 이전 서버 저장본은 유지됩니다.`)) return; const old = checkedWorkspace(await api(`snapshots/${snapshot.revision}`)); if (old.data) await persist(old.data) })}>저장본 {snapshot.revision} 복원</button>)}
      </section>
    </>}
  </main>
}
