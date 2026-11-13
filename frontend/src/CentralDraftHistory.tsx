import { useState } from 'react'

type RecordRow = { fingerprint: string; url: string; postId: number | null; source: string; createdAt: string }
type Props = { slot: string; url: string; disabled: boolean; api: (path: string, method?: string, body?: unknown) => Promise<unknown> }
export default function CentralDraftHistory({ slot, url, disabled, api }: Props) {
  const [rows, setRows] = useState<RecordRow[]>([])
  const [postId, setPostId] = useState('')
  const [message, setMessage] = useState('초안 기록은 별도로 가져옵니다. 새 글은 생성하지 않습니다.')
  const [busy, setBusy] = useState(false)
  async function run(action: () => Promise<void>) {
    setBusy(true)
    try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : '결과 미확인') }
    finally { setBusy(false) }
  }
  async function load() {
    const result = await api('draft-history') as { records: RecordRow[] }
    if (!Array.isArray(result.records)) throw new Error('초안 기록 형식 미확인')
    setRows(result.records)
  }
  async function importRecords(payload: unknown) {
    const preview = await api('draft-history/preview', 'POST', payload) as { records: { record: RecordRow }[] }
    if (!Array.isArray(preview.records)) throw new Error('미리보기 형식 미확인')
    const details = preview.records.map(item => `${item.record.url} · 글 ${item.record.postId ?? 'ID 불확실'} · ${item.record.source}`).join('\n')
    if (!window.confirm(`중앙 서버에 다음 초안 이력을 추가합니다. 기존 기록과 워드프레스 글은 변경하지 않습니다.\n${details}\n계속할까요?`)) return
    const result = await api('draft-history/import', 'POST', payload) as { added: number; existing: number; wordpressChanged: boolean }
    if (result.wordpressChanged !== false || !Number.isInteger(result.added)) throw new Error('가져오기 결과 미확인')
    await load(); setPostId(''); setMessage(`초안 이력 추가 ${result.added}개 · 기존 ${result.existing}개 · 실제 글 상태는 별도로 확인하세요.`)
  }
  return <fieldset className="central-fields" disabled={disabled || busy}><legend>기존 테스트 초안 이력</legend>
    <p>이미 저장한 글 ID를 등록하거나 별도 이력 JSON을 가져옵니다. 일반 키워드 백업에는 이 기록이 포함되지 않습니다.</p>
    <label>기존 초안 글 ID<input inputMode="numeric" value={postId} onChange={event => setPostId(event.target.value)} /></label>
    <button disabled={!/^[1-9]\d*$/.test(postId) || !Number.isSafeInteger(Number(postId)) || !url} onClick={() => void run(async () => importRecords({ format: 'zero-seo-os-draft-history', version: 1, records: [{ url, postId: Number(postId), source: '사용자 직접 등록', createdAt: '원본 시점 미확인' }] }))}>기존 글 ID 등록 미리보기</button>
    <label>초안 이력 JSON 가져오기<input type="file" accept=".json,application/json" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run(async () => { if (file.size > 5 * 1024 * 1024) throw new Error('파일은 5MB 이하여야 합니다.'); await importRecords(JSON.parse(await file.text())) }) }} /></label>
    <button onClick={() => void run(async () => { await load(); setMessage('초안 이력을 조회했습니다. 실제 글 상태는 확인 버튼으로 조회하세요.') })}>초안 이력 조회</button>
    <button disabled={!rows.length} onClick={() => {
      const payload = { format: 'zero-seo-os-draft-history', version: 1, records: rows.map(row => ({ url: row.url, postId: row.postId, source: row.source, createdAt: row.createdAt })) }
      const link = document.createElement('a')
      const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
      link.href = objectUrl; link.download = 'zero-draft-history.json'; link.click()
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
      setMessage('초안 이력 다운로드를 요청했습니다. 인증정보와 글 본문은 포함되지 않습니다.')
    }}>초안 이력 JSON 다운로드</button>
    <p role="status">{message}</p>
    {rows.map(row => <div key={row.fingerprint}><span>{row.url} · 글 {row.postId ?? 'ID 불확실'} · {row.source}</span><button disabled={row.postId === null || row.url !== url.replace(/\/$/, '')} onClick={() => void run(async () => {
      setMessage('기존 글 상태 확인 중…')
      const result = await api(`wordpress/${slot}/draft-history/${row.fingerprint}/check`, 'POST') as { draftConfirmed: boolean; postId: number; status: string; checkedAt: string }
      if (result.draftConfirmed !== true || result.postId !== row.postId || result.status !== 'draft') throw new Error('초안 상태 미확인')
      setMessage(`기존 초안 확인 · 글 ID ${result.postId} · 상태: 초안 · ${new Date(result.checkedAt).toLocaleString()} (확인 시점 기준)`)
    })}>기존 초안 상태 확인</button></div>)}
  </fieldset>
}
