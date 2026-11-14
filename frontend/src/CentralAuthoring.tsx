import { useEffect, useState } from 'react'
import type { Preparation } from './CentralKeywordBank'
type Source = { id: string; url: string; title: string; platform: string; status?: string; headings?: string[]; reason?: string }
type Document = { id: string; keyword: string; siteUrl: string; revision: number; status: string; aiConfigured: boolean; sourceOptions: Source[]; sources: Source[]; outline: string[]; draft: { title: string; body: string }; analysis: { sourceCount: number; headingCount: number; note: string; observedSignals: Record<string, number>; recurringHeadings?: { text: string; count: number }[] } | null; origin: string; unverifiedClaims?: string[] }
type Props = { preparation: Preparation; api: (path: string, method?: string, body?: unknown) => Promise<any>; onDirtyChange: (dirty: boolean) => void }
export default function CentralAuthoring({ preparation, api, onDirtyChange }: Props) {
  const [doc, setDoc] = useState<Document | null>(null)
  const [title, setTitle] = useState(''), [body, setBody] = useState(''), [outline, setOutline] = useState('')
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('작업 공간을 여는 중입니다.')
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [note, setNote] = useState('')
  const [brief, setBrief] = useState('')
  const [versions, setVersions] = useState<{ event: string; document: Document }[]>([])
  const dirty = !!doc && (title !== doc.draft.title || body !== doc.draft.body || outline !== (doc.outline || []).join('\n'))
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  function receive(value: Document) { setDoc(value); setTitle(value.draft.title); setBody(value.draft.body); setOutline((value.outline || []).join('\n')); setChecks({}); setNote(''); setBrief('') }
  useEffect(() => { let active = true; setBusy(true); api(`authoring/${preparation.id}/open`, 'POST').then(value => { if (active) { receive(value); setSourceIds(value.sourceOptions.slice(0, 3).map((r: Source) => r.id)); setMessage('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.') } }).catch(e => { if (active) setMessage(e instanceof Error ? e.message : '작업 공간 미확인') }).finally(() => { if (active) setBusy(false) }); return () => { active = false } }, [preparation.id, api])
  async function work(fn: () => Promise<void>) { if (busy) return; setBusy(true); try { await fn() } catch (e) { setMessage(e instanceof Error ? e.message : '처리 결과 미확인 · 현재 편집 내용 유지') } finally { setBusy(false) } }
  const base = `authoring/${preparation.id}`
  return <section className="panel central-authoring"><div className="central-card-heading"><div><span className="central-overline">ORIGINAL ARTICLE</span><h2>원본 글 작성 · {preparation.keyword}</h2></div><span className="central-state pending">{doc?.status === 'reviewed' && !dirty ? '수동 검토 기록 있음' : '작성·검토 준비'}</span></div><p role="status">{message}</p><p>대상 {preparation.siteUrl} · 실제 워드프레스 저장·발행은 실행하지 않습니다.</p>
    {doc && <><p>문서 버전 {doc.revision} · {dirty ? '편집 내용 미저장' : '서버 저장본 기준'} · {doc.origin === 'ai_draft' ? 'AI 초안' : doc.origin === 'manual_edit' ? '직접 편집본' : 'AI 글 미생성'}</p>
    <h3>1. 상위 글 선택·수집</h3><p>양쪽 검색에서 유형이 확인된 티스토리·워드프레스 참고 글을 최대 3개 선택합니다.</p>
    {!doc.sourceOptions.length && <p>선택 가능한 상위 글이 없습니다. 키워드 검색 근거를 먼저 확인하세요.</p>}
    {doc.sourceOptions.map(s => <label key={s.id}><input type="checkbox" aria-label={`${s.title} 참고 선택`} checked={sourceIds.includes(s.id)} disabled={busy} onChange={e => setSourceIds(old => e.target.checked ? [...old, s.id] : old.filter(v => v !== s.id))} />{s.title} · {s.platform} {/^https?:\/\//.test(s.url) && <a href={s.url} target="_blank" rel="noopener noreferrer">원문 보기</a>}</label>)}
    <button disabled={busy || dirty || !sourceIds.length || sourceIds.length > 3} onClick={() => void work(async () => { receive(await api(`${base}/research`, 'POST', { revision: doc.revision, sourceIds })); setMessage('수집 결과와 관찰 패턴을 기록했습니다. 실패한 참고 글은 미확인으로 남깁니다.') })}>선택한 상위 글 수집·구조 분석</button>
    {doc.sources.map(s => <p key={s.id}>{s.title} · {s.status === 'collected' ? '본문 일부 수집' : '수집 미확인'}{s.status !== 'collected' ? ` · ${s.reason}` : ` · 소제목 ${s.headings?.length || 0}개`}</p>)}
    {doc.analysis && <div className="central-research-summary"><h3>2. 관찰 결과·목차 설계</h3><p>수집 자료 {doc.analysis.sourceCount}개 · 소제목 {doc.analysis.headingCount}개</p><p>질문·FAQ 표현 자료 {doc.analysis.observedSignals.questions || 0}개 / 방법·절차 표현 자료 {doc.analysis.observedSignals.procedures || 0}개 / 조건·주의 표현 자료 {doc.analysis.observedSignals.conditions || 0}개</p>{!!doc.analysis.recurringHeadings?.length && <details><summary>참고 자료의 소제목 관찰</summary><ul>{doc.analysis.recurringHeadings.map((h, i) => <li key={i}>{h.text} · {h.count}회</li>)}</ul></details>}<p>{doc.analysis.note}</p><p>공식 출처에 의한 사실 확인은 별도로 필요합니다. 패턴이 노출 원인을 증명하지 않습니다.</p></div>}
    <label>작성 목차 · 한 줄에 하나<textarea aria-label="원본 글 목차" rows={6} value={outline} disabled={busy} onChange={e => setOutline(e.target.value)} /></label>
    <div className="backup-actions"><button disabled={busy || dirty || !doc.analysis?.sourceCount} onClick={() => void work(async () => { setBrief(JSON.stringify(await api(`${base}/brief`), null, 2)); setMessage('SEO·AEO·GEO 작성 지침과 참고 자료 묶음을 준비했습니다. AI 호출은 하지 않았습니다.') })}>작성 지침·참고 자료 확인</button><button disabled={busy || dirty || !doc.aiConfigured || !doc.analysis?.sourceCount} onClick={() => void work(async () => { if (body && !window.confirm('현재 저장본을 이력으로 보존하고 새 AI 초안을 만들까요?')) return; receive(await api(`${base}/generate`, 'POST', { revision: doc.revision })); setMessage('AI 초안을 저장했습니다. 사실·출처·원본성 검토가 필요합니다.') })}>AI 원본 글 생성{!doc.aiConfigured ? ' · 모델 미연결' : ''}</button></div>
    {brief && <details open><summary>작성 지침·참고 자료</summary><pre className="central-brief">{brief}</pre></details>}
    <h3>3. 원본 글 편집·검토</h3><label>글 제목<input aria-label="원본 글 제목" maxLength={200} value={title} disabled={busy} onChange={e => setTitle(e.target.value)} /></label><label>본문 · Markdown<textarea aria-label="원본 글 본문" rows={14} maxLength={50000} value={body} disabled={busy} onChange={e => setBody(e.target.value)} /></label><p>공백 제외 {body.replace(/\s/g, '').length}자 · 분량 합격 기준은 아직 설정하지 않았습니다.</p>
    <button disabled={busy || !dirty} onClick={() => void work(async () => { receive(await api(base, 'PUT', { revision: doc.revision, title, body, outline: outline.split('\n').map(v => v.trim()).filter(Boolean) })); setMessage('글과 목차를 서버에 저장했습니다. 이전 버전은 보존합니다.') })}>원본 글 편집 저장</button>
    {!!doc.unverifiedClaims?.length && <div><h4>AI가 남긴 검증 대기 항목</h4>{doc.unverifiedClaims.map((v, i) => <p key={i}>{v}</p>)}</div>}
    {Object.entries({ facts: '연락처·금액·기한 등 사실을 공식 근거로 확인했습니다.', sources: '출처와 확인 시점을 검토했습니다.', originality: '문장 복제 없이 새롭게 작성했는지 검토했습니다.', structure: '검색 의도·답변·소제목 구성을 검토했습니다.' }).map(([key, label]) => <label key={key}><input type="checkbox" aria-label={label} checked={!!checks[key]} disabled={busy} onChange={e => setChecks(old => ({ ...old, [key]: e.target.checked }))} />{label}</label>)}
    <label>검토 메모<input aria-label="원본 글 검토 메모" maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label><button disabled={busy || dirty || !doc.analysis?.sourceCount || !title.trim() || !body.trim() || !note.trim() || ['facts', 'sources', 'originality', 'structure'].some(k => !checks[k])} onClick={() => void work(async () => { receive(await api(`${base}/review`, 'POST', { revision: doc.revision, checks, note })); setMessage('본인 검토 기록을 저장했습니다. 자동 품질 인증이나 발행 성공은 아닙니다.') })}>수동 검토 완료 기록</button>
    <button disabled={busy} onClick={() => void work(async () => { setVersions((await api(`${base}/history`)).versions); setMessage('이전 저장본을 불러왔습니다. 현재 편집본은 교체하지 않았습니다.') })}>원본 글 이전 버전 보기</button>{versions.map(v => <details key={v.document.revision}><summary>버전 {v.document.revision} · {v.event}</summary><h4>{v.document.draft.title || '제목 없음'}</h4><pre className="central-brief">{v.document.draft.body || '본문 없음'}</pre></details>)}
    </>}
  </section>
}
