import { useState } from 'react'

type Props = { slot: string; url: string; disabled: boolean; api: (path: string, method?: string, body?: unknown) => Promise<unknown> }
type Result = { url: string; postId: number; status: string; draftConfirmed: boolean; checkedAt: string }
export default function CentralDraftSave({ slot, url, disabled, api }: Props) {
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('저장 결과 미확인')
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('결과 확인 중…')
    try { await action() } catch (error) { setMessage(error instanceof Error ? error.message : '저장 결과 미확인 · 재생성 전에 기록을 확인하세요.') }
    finally { setBusy(false) }
  }
  function confirmResult(value: unknown) {
    const result = value as Result
    if (result.draftConfirmed !== true || result.url !== url.replace(/\/$/, '') || result.status !== 'draft' || !Number.isSafeInteger(result.postId) || result.postId <= 0 || !result.checkedAt) throw new Error('초안 저장 결과 미확인 · 저장 시도 기록부터 확인하세요.')
    setMessage(`초안 확인 완료 · 글 ID ${result.postId} · 상태: 초안 · ${new Date(result.checkedAt).toLocaleString()} (확인 시점 기준)`)
  }
  return <fieldset className="central-fields" disabled={disabled || busy}><legend>중앙 테스트 초안 저장</legend>
    <p>연결 테스트용 고정 글을 초안으로 한 번 저장합니다. 공개 발행하지 않습니다. 기존 737·738번 등 초안이 있으면 위의 이력 등록·상태 확인을 사용하세요.</p>
    <label><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />기존 PC의 초안 이력을 확인했고, 누락된 기존 초안은 먼저 등록했습니다.</label>
    <button disabled={!reviewed || !url} onClick={() => {
      if (!window.confirm(`${url}\n워드프레스에 연결 테스트용 새 초안 1개를 저장할까요? 기존 초안이 있으면 취소하고 이력에 먼저 등록하세요. 통신 실패 시 자동 재생성하지 않습니다.`)) return
      void run(async () => confirmResult(await api(`wordpress/${slot}/test-draft`, 'POST', { url: url.replace(/\/$/, ''), confirmDraft: true, legacyHistoryReviewed: true })))
    }}>새 테스트 초안 저장</button>
    <button onClick={() => void run(async () => {
      const result = await api(`wordpress/${slot}/test-draft`) as { url: string; intent: { postId: number | null; lastConfirmedAt: string | null } | null }
      if (result.url !== url.replace(/\/$/, '')) throw new Error('사이트가 변경됐습니다. 다시 불러오세요.')
      setMessage(result.intent ? `중앙 저장 시도 기록 있음 · 글 ID ${result.intent.postId ?? '불확실'} · 새 글 생성 차단. 실제 상태는 저장 결과 재확인으로 조회하세요.` : '중앙 저장 시도 기록 없음 · 기존 PC 이력도 별도로 확인하세요.')
    })}>저장 시도 기록 조회</button>
    <button onClick={() => void run(async () => confirmResult(await api(`wordpress/${slot}/test-draft/check`, 'POST')))}>저장 결과 재확인 · 새 글 생성 안 함</button>
    <p role="status">{message}</p><p>글 ID가 불확실하면 워드프레스 글 목록에서 먼저 확인하세요. 기록 삭제나 재생성으로 복구하지 않습니다.</p>
  </fieldset>
}
