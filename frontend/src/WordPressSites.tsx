import { useEffect, useState } from 'react'

type SiteId = 'A-1' | 'A-2'
type Registration = { name: string; url: string }
type Registrations = Record<SiteId, Registration>
const STORAGE_KEY = 'zero-seo-os-sites-v1'
const EMPTY: Registrations = { 'A-1': { name: '', url: '' }, 'A-2': { name: '', url: '' } }

function normalizeUrl(raw: string) {
  const url = new URL(raw.trim())
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || (url.port && url.port !== '443')) {
    throw new Error('아이디·비밀번호·쿼리가 없는 HTTPS 사이트 주소를 입력하세요.')
  }
  return url.href.replace(/\/+$/, '')
}

function load(): Registrations {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    const result = structuredClone(EMPTY)
    for (const id of ['A-1', 'A-2'] as const) {
      if (typeof data?.[id]?.name === 'string' && typeof data?.[id]?.url === 'string' && data[id].url) {
        try { result[id] = { name: data[id].name.slice(0, 100), url: normalizeUrl(data[id].url) } }
        catch { /* One invalid registration must not discard the other site. */ }
      }
    }
    return result
  } catch { return structuredClone(EMPTY) }
}

export default function WordPressSites({ site }: { site: SiteId }) {
  const [registrations, setRegistrations] = useState(load)
  const [name, setName] = useState(registrations[site].name)
  const [url, setUrl] = useState(registrations[site].url)
  const [status, setStatus] = useState('미검증')
  const [permissionStatus, setPermissionStatus] = useState('글 작성·발행 권한 미확인')
  const [canWrite, setCanWrite] = useState(false)
  const [draftStatus, setDraftStatus] = useState('테스트 초안 상태 미확인')
  const [draftId, setDraftId] = useState<number | null>(null)
  const [confirmDraft, setConfirmDraft] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify(registrations)) }, [registrations])
  const saved = registrations[site]
  const dirty = name !== saved.name || url !== saved.url

  function resetChecks() {
    setConfirmDraft(false)
    setCanWrite(false); setDraftId(null); setDraftStatus('테스트 초안 상태 미확인')
    setStatus('미검증 · 변경 사항을 저장하세요.'); setPermissionStatus('글 작성·발행 권한 미확인')
  }

  function save() {
    try {
      if (!name.trim()) throw new Error('사이트 이름을 입력하세요.')
      const normalized = normalizeUrl(url)
      setRegistrations(prev => ({ ...prev, [site]: { name: name.trim(), url: normalized } }))
      setName(name.trim()); setUrl(normalized)
      setStatus('등록 완료 · 미검증. 서버 환경설정 후 연결을 확인하세요.')
      setPermissionStatus('글 작성·발행 권한 미확인')
      setCanWrite(false); setDraftId(null); setDraftStatus('테스트 초안 상태 미확인')
      setConfirmDraft(false)
    } catch (error) { setStatus(error instanceof Error ? error.message : '등록 실패') }
  }

  async function verify(checkPermissions = false) {
    setBusy(true); setStatus('연결 확인 중…')
    setCanWrite(false)
    setConfirmDraft(false)
    setPermissionStatus(checkPermissions ? '글 작성·발행 권한 확인 중…' : '글 작성·발행 권한 미확인')
    try {
      const endpoint = checkPermissions ? 'permissions' : 'verify'
      const response = await fetch(`http://127.0.0.1:8765/api/sites/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site, url: saved.url }), signal: AbortSignal.timeout(18000),
        cache: 'no-store', credentials: 'omit',
      })
      const data: unknown = await response.json()
      if (!data || typeof data !== 'object') throw new Error('서버 응답 형식 오류')
      const result = data as Record<string, unknown>
      if (!response.ok || result.verified !== true || result.site !== site || result.url !== saved.url || typeof result.checkedAt !== 'string') {
        throw new Error(typeof result.message === 'string' ? result.message : '인증 연결을 확인하지 못했습니다.')
      }
      setStatus(`인증 연결 검증 성공 · ${new Date(result.checkedAt).toLocaleString()} (확인 시점 기준)`)
      if (checkPermissions) {
        const permissions = result.permissions
        if (!permissions || typeof permissions !== 'object' || result.permissionBasis !== 'wordpress-user-capabilities') {
          setPermissionStatus('권한 확인 불가 · 서버 업데이트 및 재실행을 확인하세요.')
        } else {
          const caps = permissions as Record<string, unknown>
          const describe = (value: unknown) => value === true ? '있음' : value === false ? '없음' : '확인 불가'
          setPermissionStatus(`글 작성 권한: ${describe(caps.editPosts)} / 글 발행 권한: ${describe(caps.publishPosts)} · 워드프레스 사용자 권한 기준. 실제 저장·발행 결과와는 별도입니다.`)
          setCanWrite(caps.editPosts === true)
        }
      }
    } catch (error) {
      setStatus(`미연결 · ${error instanceof TypeError ? '연결 서버를 실행했는지 확인하세요.' : error instanceof Error ? error.message : '검증 실패'}`)
      setPermissionStatus('글 작성·발행 권한 미확인')
    } finally { setBusy(false) }
  }

  async function saveTestDraft(confirmed = false) {
    if (busy || dirty || !canWrite || !saved.url) return
    if (!draftId && !confirmed) { setConfirmDraft(true); return }
    if (confirmed && !confirmDraft) return
    setConfirmDraft(false)
    setBusy(true); setDraftStatus('테스트 초안 저장·상태 확인 중…')
    try {
      const response = await fetch('http://127.0.0.1:8765/api/sites/test-draft', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site, url: saved.url }), signal: AbortSignal.timeout(45000),
        cache: 'no-store', credentials: 'omit',
      })
      const data: unknown = await response.json()
      if (!data || typeof data !== 'object') throw new Error('서버 응답 형식 오류')
      const result = data as Record<string, unknown>
      if (!response.ok || result.draftConfirmed !== true || result.site !== site || result.url !== saved.url || result.status !== 'draft' || typeof result.postId !== 'number' || !Number.isSafeInteger(result.postId) || result.postId <= 0 || typeof result.checkedAt !== 'string') {
        throw new Error(typeof result.message === 'string' ? result.message : '초안 저장 결과를 확인하지 못했습니다.')
      }
      setDraftId(result.postId)
      setDraftStatus(`${result.reused === true ? '기존 테스트 초안 확인' : '테스트 초안 저장 확인'} · 글 ID ${result.postId} · 상태: 초안 · ${new Date(result.checkedAt).toLocaleString()} (확인 시점 기준)`)
    } catch (error) {
      setDraftId(null)
      const detail = error instanceof TypeError ? '연결 서버를 확인하세요.' : error instanceof Error ? error.message : '알 수 없는 오류'
      setDraftStatus(`저장·상태 확인 실패 · ${detail} 자동 재시도하지 않습니다. 워드프레스 글 목록을 먼저 확인하세요.`)
    } finally { setBusy(false) }
  }

  return <section className="panel wp-panel">
    <div className="panel-heading"><div><h2>{site} 워드프레스 사이트</h2><p>사이트 등록 후 서버를 통해 실제 인증을 검증합니다.</p></div><span className="tag">v0.2.2</span></div>
    <div className="wp-fields">
      <label>사이트 이름<input maxLength={100} value={name} disabled={busy} onChange={e => { setName(e.target.value); resetChecks() }} /></label>
      <label>워드프레스 주소<input type="url" placeholder="https://example.com" value={url} disabled={busy} onChange={e => { setUrl(e.target.value); resetChecks() }} /></label>
    </div>
    <div className="backup-actions"><button onClick={save} disabled={busy}>사이트 등록·저장</button><button onClick={() => void verify()} disabled={busy || dirty || !saved.url}>실제 연결 확인</button><button onClick={() => void verify(true)} disabled={busy || dirty || !saved.url}>글 작성·발행 권한 확인</button></div>
    <p role="status" aria-live="polite">{status}</p>
    <p role="status" aria-live="polite">{permissionStatus}</p>
    <div className="wp-draft-test">
      <h3>테스트 초안 저장</h3>
      <p>대상: {saved.name || site} · {saved.url || '사이트를 먼저 등록하세요.'}</p>
      <p>제목: [ZERO SEO OS] 연결 테스트 초안</p>
      <p>본문: ZERO SEO OS와 워드프레스의 초안 저장 연결을 확인하기 위한 테스트 글입니다.</p>
      <button onClick={() => void saveTestDraft()} disabled={busy || dirty || !canWrite || !saved.url || confirmDraft}>{draftId ? '테스트 초안 상태 확인' : '테스트 초안 1개 저장'}</button>
      {confirmDraft && <div role="dialog" aria-labelledby="confirm-draft-title" className="wp-draft-confirm">
        <h4 id="confirm-draft-title">테스트 초안 저장 확인</h4>
        <p>{site} · {saved.name} · {saved.url}</p>
        <p>위 제목과 본문으로 테스트 글 1개를 초안으로 저장합니다. 공개 발행하지 않습니다. 이전 저장 기록이 있으면 새로 만들지 않고 기존 글을 확인합니다.</p>
        <button disabled={busy} onClick={() => void saveTestDraft(true)}>확인하고 초안 저장</button>{' '}
        <button disabled={busy} onClick={() => setConfirmDraft(false)}>취소</button>
      </div>}
      <p role="status" aria-live="polite">{draftStatus}</p>
      {draftId && <a href={`${saved.url}/wp-admin/post.php?post=${draftId}&action=edit`} target="_blank" rel="noopener noreferrer">워드프레스에서 초안 확인</a>}
      <p className="queue-note">먼저 글 작성·발행 권한을 확인하세요. 테스트 글은 초안으로만 요청하며, 서버 기록이 유지되는 동안 같은 사이트에 중복 생성하지 않습니다. 기존 키워드·작업 대기열과 별도로 진행합니다.</p>
    </div>
    <p className="queue-note">브라우저에는 이름과 주소만 저장합니다. 앱 비밀번호는 Python 서버 환경변수로 설정하세요. 새로고침하면 다시 검증해야 합니다. 기존 JSON 백업은 키워드·작업 전용이며 사이트 설정은 포함하지 않습니다.</p>
  </section>
}

