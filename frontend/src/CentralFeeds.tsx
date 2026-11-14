import { useState } from 'react'
type Candidate = { text: string; sources: { postUrl: string; sourceType: string }[] }
type Collection = { id: string; blogUrl: string; feedUrl?: string; createdAt: string; status: string; reason?: string; posts: { title: string; url: string }[]; candidates: Candidate[]; truncated?: boolean }
type Props = { api: (path: string, method?: string, body?: unknown) => Promise<any> }
export default function CentralFeeds({ api }: Props) {
  const [url, setUrl] = useState('')
  const [records, setRecords] = useState<Collection[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('블로그 주소로 시작할 수 있습니다. 검색 API 없이 RSS만 읽습니다.')
  async function perform(action: () => Promise<void>) { if (busy) return; setBusy(true); try { await action() } catch (e) { setMessage(e instanceof Error ? e.message : '수집 결과 미확인') } finally { setBusy(false) } }
  return <section className="panel"><h2>RSS 수집 · 키워드 후보 추출</h2><p>3단계 · 공개 피드의 글 제목과 분류를 후보로 모읍니다. 검색량·노출 여부로 선별하지 않습니다.</p><p role="status">{message}</p>
    <form className="keyword-form" onSubmit={e => { e.preventDefault(); void perform(async () => { setMessage('공개 RSS를 찾고 글 목록을 읽고 있습니다.'); const result = await api('feed-collections', 'POST', { blogUrl: url }); setRecords(old => [result, ...old.filter(r => r.id !== result.id)]); setMessage(result.status === 'collected' ? `글 ${result.posts.length}개 · 검토 전 후보 ${result.candidates.length}개 수집·서버 저장 확인` : result.status === 'empty' ? '피드는 확인했으나 수집 가능한 글이 없습니다. 기존 기록은 유지됩니다.' : '수집 미완료 · 이전 기록은 유지되며 실패 이유를 기록했습니다.') }) }}>
      <input aria-label="RSS를 수집할 블로그 주소" type="url" placeholder="https://example.com/" value={url} onChange={e => setUrl(e.target.value)} disabled={busy} />
      <button type="submit" disabled={busy || !url.trim()}>RSS 수집 시작</button><button type="button" disabled={busy} onClick={() => void perform(async () => { const result = await api('feed-collections'); if (!Array.isArray(result.collections)) throw new Error('수집 기록 형식 미확인'); setRecords(result.collections); setMessage('서버의 최근 수집 기록을 불러왔습니다.') })}>RSS 수집 기록 불러오기</button>
    </form><p>한 번에 피드 최대 500개 항목을 읽습니다. 피드의 공개 범위에 제한되며 전체 글 수집을 보장하지 않습니다. 제목 기반 후보는 검색용 핵심어 검토가 필요합니다.</p>
    {records.map(r => <article key={r.id} className="panel"><h3>{r.blogUrl}</h3><p>{r.status === 'collected' ? '수집 완료 · 선별 전' : r.status === 'empty' ? '글 없음' : '수집 미완료'} · {new Date(r.createdAt).toLocaleString('ko-KR')}</p><p>{r.feedUrl || r.reason}</p>{r.truncated && <p>500개 항목 제한으로 일부만 처리했습니다.</p>}<p>글 {r.posts.length}개 / 후보 {r.candidates.length}개 · 검색량 미측정 · 네이버·구글 노출 미검증</p>
      {r.candidates.length > 200 && <p>화면에는 처음 200개를 표시합니다. 전체 결과는 내려받을 수 있습니다.</p>}
      {r.candidates.slice(0, 200).map((c, i) => <div className="keyword-item" key={i}><strong>{c.text}</strong><span>검토 전 후보 · 출처 {c.sources.length}개</span><span>{c.sources[0]?.sourceType === 'post_title' ? '글 제목' : '피드 분류'}</span></div>)}
      <button onClick={() => { const blob = URL.createObjectURL(new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = blob; a.download = `zero-rss-${r.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(blob), 1000) }}>수집 결과 JSON 내려받기</button>
    </article>)}
  </section>
}
