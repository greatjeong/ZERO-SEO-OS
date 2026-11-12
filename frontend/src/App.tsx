import { useEffect, useRef, useState } from 'react'
import './App.css'
import WordPressSites from './WordPressSites'

type Site = 'A-1' | 'A-2'
type KeywordData = Record<Site, string[]>
type JobStatus = '대기' | '진행 중' | '재시도 대기' | '검토·보류' | '발행 예약' | '완료' | '실패' | '취소'
type Job = { id: string; site: Site; keyword: string; status: JobStatus; createdAt: string }
const KEYWORD_KEY = 'zero-seo-os-keywords-v1'
const JOB_KEY = 'zero-seo-os-jobs-v1'
const ALL_STATUSES: JobStatus[] = ['대기', '진행 중', '재시도 대기', '검토·보류', '발행 예약', '완료', '실패', '취소']

function loadKeywords(): KeywordData {
  const empty: KeywordData = { 'A-1': [], 'A-2': [] }
  try {
    const raw = localStorage.getItem(KEYWORD_KEY)
    if (!raw) return empty
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return empty
    const data = parsed as Record<string, unknown>
    return {
      'A-1': Array.isArray(data['A-1']) ? data['A-1'].filter((v): v is string => typeof v === 'string') : [],
      'A-2': Array.isArray(data['A-2']) ? data['A-2'].filter((v): v is string => typeof v === 'string') : [],
    }
  } catch { return empty }
}

function loadJobs(): Job[] {
  try {
    const raw = localStorage.getItem(JOB_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((j): j is Job =>
      j && typeof j === 'object' && typeof j.id === 'string' &&
      (j.site === 'A-1' || j.site === 'A-2') && typeof j.keyword === 'string' &&
      typeof j.createdAt === 'string' &&
      ALL_STATUSES.includes(j.status)
    )
  } catch { return [] }
}

function App() {
  const [site, setSite] = useState<Site>('A-1')
  const [keywordsBySite, setKeywordsBySite] = useState<KeywordData>(loadKeywords)
  const [jobs, setJobs] = useState<Job[]>(loadJobs)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [jobFilter, setJobFilter] = useState('전체')
  const [backupStatus, setBackupStatus] = useState('백업 JSON 파일을 선택하면 복원 결과가 여기에 표시됩니다.')
  const importRef = useRef<HTMLInputElement>(null)
  const keywords = keywordsBySite[site]
  const siteJobs = jobs.filter((j) => j.site === site)
  const visibleJobs = siteJobs.filter((j) => jobFilter === '전체' || j.status === jobFilter)
  const waiting = siteJobs.filter((j) => j.status === '대기').length
  const filteredKeywords = keywords.filter((item) => item.toLowerCase().includes(search.trim().toLowerCase()))

  useEffect(() => { localStorage.setItem(KEYWORD_KEY, JSON.stringify(keywordsBySite)) }, [keywordsBySite])
  useEffect(() => { localStorage.setItem(JOB_KEY, JSON.stringify(jobs)) }, [jobs])

  function changeSite(next: Site) {
    setSite(next); setKeyword(''); setSearch(''); setSelected([]); setMessage(''); setJobFilter('전체')
  }
  function addKeyword() {
    const value = keyword.trim()
    if (!value) { setMessage('등록할 키워드를 입력해 주세요.'); return }
    if (keywords.some((item) => item.toLowerCase() === value.toLowerCase())) {
      setMessage('이미 등록된 키워드입니다.'); return
    }
    setKeywordsBySite((prev) => ({ ...prev, [site]: [...prev[site], value] }))
    setKeyword(''); setMessage('키워드가 등록되었습니다.')
  }
  function deleteKeyword(value: string) {
    setKeywordsBySite((prev) => ({ ...prev, [site]: prev[site].filter((item) => item !== value) }))
    setSelected((prev) => prev.filter((item) => item !== value))
    setMessage('키워드를 삭제했습니다. 기존 작업 기록은 유지됩니다.')
  }
  function toggleKeyword(value: string) {
    setSelected((prev) => prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value])
  }
  function toggleAll() {
    if (!filteredKeywords.length) return
    const allSelected = filteredKeywords.every((item) => selected.includes(item))
    setSelected((prev) => allSelected ? prev.filter((item) => !filteredKeywords.includes(item)) : [...new Set([...prev, ...filteredKeywords])])
  }
  function deleteSelected() {
    const targets = selected.filter((item) => keywords.includes(item))
    if (!targets.length) { setMessage('삭제할 키워드를 먼저 선택해 주세요.'); return }
    if (!window.confirm(`${targets.length}개의 키워드를 삭제하시겠습니까?`)) return
    setKeywordsBySite((prev) => ({ ...prev, [site]: prev[site].filter((item) => !targets.includes(item)) }))
    setSelected([]); setMessage(`${targets.length}개의 키워드를 삭제했습니다. 기존 작업 기록은 유지됩니다.`)
  }
  function deleteAll() {
    if (!keywords.length) { setMessage('삭제할 키워드가 없습니다.'); return }
    if (!window.confirm(`${site} 사이트의 모든 키워드를 삭제하시겠습니까?`)) return
    setKeywordsBySite((prev) => ({ ...prev, [site]: [] }))
    setSelected([]); setMessage('모든 키워드를 삭제했습니다. 기존 작업 기록은 유지됩니다.')
  }
  function enqueueJobs() {
    const targets = keywords.filter((item) => selected.includes(item))
    if (!targets.length) { setMessage('작업에 추가할 키워드를 선택해 주세요.'); return }
    const active = new Set(jobs.filter((j) => j.site === site && j.status === '대기').map((j) => j.keyword.toLowerCase()))
    const fresh = targets.filter((item) => !active.has(item.toLowerCase()))
    if (!fresh.length) { setMessage('선택한 키워드는 이미 대기열에 있습니다.'); return }
    const createdAt = new Date().toISOString()
    setJobs((prev) => [
      ...fresh.map((item) => ({ id: crypto.randomUUID(), site, keyword: item, status: '대기' as const, createdAt })),
      ...prev,
    ])
    setSelected([])
    setMessage(`${fresh.length}개 작업을 대기열에 추가했습니다. AI 생성은 아직 실행되지 않습니다.`)
  }
  function cancelJob(id: string) {
    setJobs((prev) => prev.map((job) => job.id === id && job.status === '대기' ? { ...job, status: '취소' } : job))
  }
  function retryCancelled(id: string) {
    const target = jobs.find((j) => j.id === id && j.site === site && j.status === '취소')
    if (!target) return
    const exists = jobs.some((j) => j.site === site && j.status === '대기' && j.keyword.toLowerCase() === target.keyword.toLowerCase())
    if (exists) { setMessage('동일 키워드의 대기 작업이 이미 존재합니다.'); return }
    setJobs((prev) => prev.map((j) => j.id === id ? { ...j, status: '대기' } : j))
    setMessage('취소한 작업을 다시 대기열에 등록했습니다. 자동 실행되지는 않습니다.')
  }

  function exportBackup() {
    const data = { format: 'zero-seo-os-backup', version: 1, exportedAt: new Date().toISOString(), keywordsBySite, jobs }
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `zero-seo-os-backup-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setMessage('백업 파일 다운로드를 요청했습니다. 다운로드 폴더를 확인해 주세요.')
  }

  async function importBackup(file: File | undefined) {
    if (!file) { setBackupStatus('파일이 선택되지 않았습니다.'); return }
    setBackupStatus(`파일 확인 중: ${file.name}`)
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('백업 파일은 5MB 이하여야 합니다.')
      const data: unknown = JSON.parse(await file.text())
      if (!data || typeof data !== 'object') throw new Error('백업 형식이 올바르지 않습니다.')
      const backup = data as Record<string, unknown>
      if (backup.format !== 'zero-seo-os-backup' || backup.version !== 1) throw new Error('ZERO SEO OS v1 백업 파일만 복원할 수 있습니다.')
      const rawKeywords = backup.keywordsBySite
      if (!rawKeywords || typeof rawKeywords !== 'object') throw new Error('키워드 데이터가 없습니다.')
      const keywordData = rawKeywords as Record<string, unknown>
      const isStringArray = (value: unknown): value is string[] => Array.isArray(value) && value.every((v) => typeof v === 'string')
      if (!isStringArray(keywordData['A-1']) || !isStringArray(keywordData['A-2'])) throw new Error('사이트별 키워드 형식이 올바르지 않습니다.')
      if (!Array.isArray(backup.jobs)) throw new Error('작업 기록 형식이 올바르지 않습니다.')
      const isJob = (value: unknown): value is Job => {
        if (!value || typeof value !== 'object') return false
        const j = value as Record<string, unknown>
        return typeof j.id === 'string' && (j.site === 'A-1' || j.site === 'A-2') && typeof j.keyword === 'string' && typeof j.createdAt === 'string' && ALL_STATUSES.includes(j.status as JobStatus)
      }
      if (!backup.jobs.every(isJob)) throw new Error('작업 기록에 잘못된 항목이 있습니다.')
      const ids = backup.jobs.map((j: Job) => j.id)
      if (new Set(ids).size !== ids.length) throw new Error('작업 ID가 중복되어 있습니다.')
      setBackupStatus(`파일 검사 완료: A-1 ${keywordData['A-1'].length}개 / A-2 ${keywordData['A-2'].length}개 / 작업 ${backup.jobs.length}개`)
      if (!window.confirm('현재 A-1/A-2 키워드와 작업 기록을 백업 파일 내용으로 모두 교체합니다. 계속하시겠습니까?')) {
        setBackupStatus('복원을 취소했습니다. 현재 데이터는 변경되지 않았습니다.')
        return
      }
      setKeywordsBySite({ 'A-1': [...keywordData['A-1']], 'A-2': [...keywordData['A-2']] })
      setJobs(backup.jobs)
      setSelected([])
      setSearch('')
      setJobFilter('전체')
      setMessage('백업 파일을 복원했습니다. A-1/A-2 데이터를 확인해 주세요.')
      setBackupStatus(`복원 완료: A-1 ${keywordData['A-1'].length}개 / A-2 ${keywordData['A-2'].length}개 / 작업 ${backup.jobs.length}개`)
    } catch (error) {
      const detail = error instanceof Error ? error.message : '알 수 없는 오류'
      setMessage(`복원 실패: ${detail}`)
      setBackupStatus(`복원 실패: ${detail}`)
    } finally {
      if (importRef.current) importRef.current.value = ''
    }
  }


  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">ZERO <span>SEO OS</span></div>
        <p className="sidebar-label">WORKSPACE</p>
        <nav>
          <button className="nav-active">▦ 대시보드</button>
          <button>⌕ 키워드 관리</button>
          <button>✦ AI 콘텐츠</button>
          <button>▤ 발행 관리</button>
          <button>◷ 작업 기록</button>
          <button>⚙ 설정</button>
        </nav>
        <div className="sidebar-bottom">ZERO SEO OS · v0.2.2</div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">OVERVIEW</p>
            <h1>통합 대시보드</h1>
            <p className="subtitle">키워드부터 콘텐츠 제작과 발행까지 한곳에서 관리하세요.</p>
          </div>
          <div className="site-switch">
            <button className={site === 'A-1' ? 'selected' : ''} onClick={() => changeSite('A-1')}>A-1 사이트</button>
            <button className={site === 'A-2' ? 'selected' : ''} onClick={() => changeSite('A-2')}>A-2 사이트</button>
          </div>
        </header>
        <section className="notice">
          <span className="notice-dot" />
          <strong>{site} 작업 공간</strong>
          <span>현재 선택한 사이트의 운영 현황입니다.</span>
          <span className="demo-tag">로컬 개발 버전</span>
        </section>
        {message && <p className="global-message" role="status">{message}</p>}
        <WordPressSites key={site} site={site} />
        <section className="stats">
          <article className="stat-card"><span>등록된 키워드</span><strong>{keywords.length}</strong><small>현재 사이트 기준</small></article>
          <article className="stat-card"><span>AI 콘텐츠 생성</span><strong>0</strong><small>AI 연동 전</small></article>
          <article className="stat-card"><span>발행 완료</span><strong>0</strong><small>워드프레스 연결 예정</small></article>
          <article className="stat-card"><span>대기 중인 작업</span><strong>{waiting}</strong><small>현재 사이트 기준 · 수동 등록</small></article>
        </section>
        <div className="content-grid">
          <section className="panel">
            <div className="panel-heading"><div><h2>키워드 관리</h2><p>콘텐츠를 제작할 키워드를 등록하세요.</p></div><span className="tag">STEP 01</span></div>
            <form className="keyword-form" onSubmit={(e) => { e.preventDefault(); addKeyword() }}>
              <input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="예: 워드프레스 SEO 최적화" />
              <button type="submit">+ 등록</button>
            </form>
            <div className="keyword-tools">
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="등록된 키워드 검색" />
              <button type="button" onClick={toggleAll} disabled={!filteredKeywords.length}>
                {filteredKeywords.length > 0 && filteredKeywords.every((item) => selected.includes(item)) ? '선택 해제' : '전체 선택'}
              </button>
              <button type="button" onClick={deleteSelected}>선택 삭제</button>
              <button type="button" onClick={deleteAll}>전체 삭제</button>
            </div>
            <div className="keyword-list">
              {!filteredKeywords.length ? <div className="empty">{!keywords.length ? '아직 등록된 키워드가 없습니다.' : '검색 결과가 없습니다.'}</div> :
                filteredKeywords.map((item) => (
                  <div className="keyword-item" key={item}>
                    <label className="keyword-check"><input type="checkbox" checked={selected.includes(item)} onChange={() => toggleKeyword(item)} /><span>{item}</span></label>
                    <button type="button" onClick={() => deleteKeyword(item)}>삭제</button>
                  </div>
                ))}
            </div>
            <p className="keyword-summary">전체 {keywords.length}개 · 선택 {selected.length}개</p>
          </section>
          <section className="panel">
            <div className="panel-heading"><div><h2>AI 콘텐츠 제작</h2><p>선택한 키워드를 작업 대기열에 등록합니다.</p></div><span className="tag">STEP 02</span></div>
            <div className="workflow">
              <div><span>01</span> 키워드 선택 <em>{selected.length}개 선택</em></div>
              <div><span>02</span> 검색 결과 분석 <em>연결 예정</em></div>
              <div><span>03</span> AI 콘텐츠 생성 <em>연결 예정</em></div>
              <div><span>04</span> SEO 품질 점검 <em>연결 예정</em></div>
              <div><span>05</span> 워드프레스 발행 <em>연결 예정</em></div>
            </div>
            <button className="enqueue-button" type="button" onClick={enqueueJobs} disabled={!selected.length}>
              선택 키워드 {selected.length}개 작업 대기열에 추가
            </button>
            <p className="queue-note">현재는 작업 등록만 가능합니다. AI 콘텐츠는 생성되지 않습니다.</p>
          </section>
        </div>
        <section className="panel bottom-panel">
          <div className="panel-heading"><div><h2>최근 작업 현황</h2><p>{site} 사이트의 작업 대기열과 취소 기록</p></div><span className="tag">ACTIVITY</span></div>
          <div className="job-filter-bar">
            <label htmlFor="job-filter">작업 상태</label>
            <select id="job-filter" value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
              <option value="전체">전체</option>
              {ALL_STATUSES.map((status) => <option value={status} key={status}>{status}</option>)}
            </select>
            <span>{visibleJobs.length}개 표시 / 전체 {siteJobs.length}개</span>
          </div>
          {!visibleJobs.length ? <div className="activity-empty">{siteJobs.length ? '해당 상태의 작업이 없습니다.' : '아직 등록된 작업이 없습니다.'}</div> :
            <div className="job-list">
              {visibleJobs.map((job) => (
                <div className="job-item" key={job.id}>
                  <div className="job-info"><strong>{job.keyword}</strong><small>{new Date(job.createdAt).toLocaleString('ko-KR')}</small></div>
                  <span className={`job-status ${job.status === '취소' ? 'job-cancelled' : ''}`}>{job.status}</span>
                  {job.status === '대기' && <button type="button" className="job-cancel" onClick={() => cancelJob(job.id)}>취소</button>}
                  {job.status === '취소' && <button type="button" className="job-cancel" onClick={() => retryCancelled(job.id)}>다시 대기</button>}
                </div>
              ))}
            </div>}
        </section>
        <section className="panel bottom-panel">
          <div className="panel-heading"><div><h2>로컬 데이터 백업</h2><p>A-1/A-2 키워드와 작업 기록을 파일로 보관합니다.</p></div><span className="tag">BACKUP</span></div>
          <div className="backup-actions">
            <button type="button" onClick={exportBackup}>전체 데이터 백업 다운로드</button>
            <label className="backup-file-label" htmlFor="zero-backup-file">복원할 JSON 파일 선택</label>
            <input id="zero-backup-file" ref={importRef} type="file" accept=".json,application/json" aria-label="ZERO SEO OS 백업 JSON 파일" onChange={(e) => { void importBackup(e.target.files?.[0]) }} />
          </div>
          <p className="backup-result" role="status" aria-live="polite">{backupStatus}</p>
          <p className="queue-note">복원하면 현재 브라우저의 두 사이트 데이터가 모두 교체됩니다. 중요한 데이터는 먼저 백업하세요. JSON 백업 파일에는 키워드가 평문으로 저장됩니다.</p>
        </section>
      </main>
    </div>
  )
}

export default App



