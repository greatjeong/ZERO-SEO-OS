import { beforeEach, afterEach, test, expect, vi } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import CentralApp from '../src/CentralApp'

const data = { format: 'zero-seo-os-backup', version: 2, exportedAt: '2026-11-13', sites: { 'A-1': { name: '서버 사이트', url: 'https://example.com' }, 'A-2': { name: '', url: '' } }, keywordsBySite: { 'A-1': ['기존 키워드'], 'A-2': ['분리 키워드'] }, jobs: [] }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name, exact: true }))
function signedIn() {
  vi.mocked(fetch).mockResolvedValueOnce(json({ authenticated: true, csrf: 'test-csrf' })).mockResolvedValueOnce(json({ revision: 1, data: structuredClone(data) }))
  render(<CentralApp />)
  return screen.findByText('기존 키워드', { exact: true })
}
function add(value: string) { fireEvent.change(screen.getByLabelText('등록할 키워드'), { target: { value } }); click('키워드 등록') }
beforeEach(() => { vi.stubGlobal('fetch', vi.fn()); localStorage.clear() })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

test('central mode never reads or writes local browser data', async () => {
  const read = vi.spyOn(Storage.prototype, 'getItem')
  const write = vi.spyOn(Storage.prototype, 'setItem')
  await signedIn()
  add('새 키워드')
  click('A-2 사이트')
  expect(screen.queryByText('새 키워드', { exact: true })).toBeNull()
  expect(screen.getByText('분리 키워드')).toBeTruthy()
  expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled()
})

test('anonymous user sees login and only session bootstrap request', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: '로그인 필요' }, 401))
  render(<CentralApp />)
  await screen.findByRole('heading', { name: '본인 로그인' })
  expect(screen.queryByText('키워드 관리', { exact: true })).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('login sends password once, same-origin session, and loads server workspace', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: '로그인 필요' }, 401))
  render(<CentralApp />)
  await screen.findByRole('heading', { name: '본인 로그인' })
  vi.mocked(fetch).mockResolvedValueOnce(json({ authenticated: true, csrf: 'csrf-after-login' })).mockResolvedValueOnce(json({ revision: 1, data }))
  fireEvent.change(screen.getByLabelText('서비스 비밀번호'), { target: { value: 'test-only-owner-password' } }); click('로그인')
  await screen.findByText('기존 키워드', { exact: true })
  const call = vi.mocked(fetch).mock.calls[1]
  expect(call[0]).toBe('/api/login'); expect(call[1]?.credentials).toBe('same-origin')
  expect(localStorage.length).toBe(0)
  expect(screen.queryByDisplayValue('test-only-owner-password')).toBeNull()
})

test('failed save retains edits and successful save uses revision and CSRF', async () => {
  await signedIn(); add('보존할 변경')
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: '서버 장애' }, 503))
  click('변경 사항 서버 저장'); await screen.findByText('서버 장애', { exact: true })
  expect(screen.getByText('보존할 변경', { exact: true })).toBeTruthy()
  expect(screen.queryByText(/서버 저장 확인/)).toBeNull()
  const changed = { ...data, keywordsBySite: { ...data.keywordsBySite, 'A-1': ['기존 키워드', '보존할 변경'] } }
  vi.mocked(fetch).mockResolvedValueOnce(json({ revision: 2, data: changed }))
  click('변경 사항 서버 저장'); await screen.findByText(/서버 저장 확인 · 버전 2/)
  const call = vi.mocked(fetch).mock.calls.at(-1)!
  expect(JSON.parse(call[1]?.body as string).baseRevision).toBe(1)
  expect(((call[1]?.headers || {}) as Record<string, string>)['X-CSRF-Token']).toBe('test-csrf')
})

test('conflict never replaces unsaved edits or automatically retries', async () => {
  await signedIn(); add('충돌 변경')
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: '다른 창에서 먼저 저장했습니다.' }, 409))
  click('변경 사항 서버 저장'); await screen.findByText('다른 창에서 먼저 저장했습니다.', { exact: true })
  expect(screen.getByText('충돌 변경', { exact: true })).toBeTruthy()
  expect(vi.mocked(fetch).mock.calls.filter(call => call[0] !== '/api/discovery')).toHaveLength(3)
})

test('backup import preview cancellation never writes', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({ baseRevision: 1, data, counts: { 'A-1': 1, 'A-2': 1 }, jobs: 0 }))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  const file = new File([], 'backup.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify({ ...data, version: 1 }) })
  fireEvent.change(screen.getByLabelText('v1/v2 JSON 가져오기'), { target: { files: [file] } })
  await waitFor(() => expect(window.confirm).toHaveBeenCalled())
  expect(vi.mocked(fetch).mock.calls.filter(call => call[0] !== '/api/discovery')).toHaveLength(3)
  expect(vi.mocked(fetch).mock.calls.at(-1)![0]).toBe('/api/import/preview')
  expect(screen.getByText('기존 키워드', { exact: true })).toBeTruthy()
})

test('missing workspace is not silently initialized', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ authenticated: true, csrf: 'csrf' })).mockResolvedValueOnce(json({ revision: 0, data: null }))
  render(<CentralApp />)
  await screen.findByRole('heading', { name: '서버 작업 공간이 비어 있습니다' })
  expect(vi.mocked(fetch).mock.calls.filter(call => call[0] !== '/api/discovery')).toHaveLength(2)
  expect(screen.getByRole('button', { name: '빈 작업 공간으로 시작' })).toBeTruthy()
})

test('unsaved server edits warn before browser reload', async () => {
  await signedIn()
  const before = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(before); expect(before.defaultPrevented).toBe(false)
  add('저장 전 변경')
  const after = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(after); expect(after.defaultPrevented).toBe(true)
})

test('WordPress credentials clear after save and success requires verification', async () => {
  await signedIn()
  fireEvent.change(screen.getByLabelText('워드프레스 사용자명'), { target: { value: 'owner' } })
  fireEvent.change(screen.getByLabelText('앱 비밀번호'), { target: { value: 'abcdefghijklmnopqrstuvwx' } })
  vi.mocked(fetch).mockResolvedValueOnce(json({ configured: true, verified: false }))
  click('인증정보 암호화 저장')
  await screen.findByText('암호화 저장 확인 · 실제 연결 확인을 눌러주세요.')
  expect((screen.getByLabelText('앱 비밀번호') as HTMLInputElement).value).toBe('')
  expect(screen.queryByText(/인증 연결 검증 성공/)).toBeNull()
  vi.mocked(fetch).mockResolvedValueOnce(json({ verified: true, url: 'https://example.com', checkedAt: '2026-11-13T00:00:00Z', permissions: { editPosts: true, publishPosts: null } }))
  click('실제 연결 확인')
  await screen.findByText(/인증 연결 검증 성공/)
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: 'HTTP 401' }, 502))
  click('실제 연결 확인')
  await screen.findByText('HTTP 401')
  expect(screen.queryByText(/인증 연결 검증 성공/)).toBeNull()
})

test('existing draft registration requires preview confirmation and never creates posts', async () => {
  await signedIn()
  fireEvent.change(screen.getByLabelText('기존 초안 글 ID'), { target: { value: '738' } })
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false)
  vi.mocked(fetch).mockResolvedValueOnce(json({ records: [{ record: { url: 'https://example.com', postId: 738, source: '사용자 직접 등록' } }] }))
  click('기존 글 ID 등록 미리보기')
  await waitFor(() => expect(window.confirm).toHaveBeenCalled())
  expect(vi.mocked(fetch).mock.calls.filter(call => String(call[0]).includes('draft-history/import'))).toHaveLength(0)
  expect(vi.mocked(fetch).mock.calls.some(call => String(call[0]).includes('/posts'))).toBe(false)
})

test('new draft requires history acknowledgment and explicit confirmation', async () => {
  await signedIn()
  expect((screen.getByRole('button', { name: '새 테스트 초안 저장' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  click('새 테스트 초안 저장')
  expect(window.confirm).toHaveBeenCalled()
  expect(vi.mocked(fetch).mock.calls.some(call => String(call[0]).endsWith('/test-draft'))).toBe(false)
})

test('draft readback success is removed when the next check fails', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({ url: 'https://example.com', postId: 900, status: 'draft', draftConfirmed: true, checkedAt: '2026-11-13T00:00:00Z' }))
  click('저장 결과 재확인 · 새 글 생성 안 함')
  await screen.findByText(/초안 확인 완료 · 글 ID 900/)
  vi.mocked(fetch).mockResolvedValueOnce(json({ message: '저장 결과 불확실' }, 502))
  click('저장 결과 재확인 · 새 글 생성 안 함')
  await screen.findByText('저장 결과 불확실')
  expect(screen.queryByText(/초안 확인 완료 · 글 ID 900/)).toBeNull()
})

test('four menu shell preserves unsaved site inputs across page changes', async () => {
  await signedIn()
  fireEvent.change(screen.getByLabelText('사이트 이름'), { target: { value: '수정 중인 이름' } })
  click('PBN 세팅')
  expect(screen.getByRole('heading', { name: 'PBN 세팅 · 준비 중' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '인증정보 암호화 저장' })).toBeNull()
  click('백링크 세팅')
  expect(screen.getByRole('heading', { name: '백링크 세팅 · 준비 중' })).toBeTruthy()
  click('통합 관리')
  expect((screen.getByLabelText('사이트 이름') as HTMLInputElement).value).toBe('수정 중인 이름')
  expect(screen.getByRole('button', { name: '변경 사항 서버 저장' }).hasAttribute('disabled')).toBe(false)
  expect(vi.mocked(fetch).mock.calls.some(call => ['POST','PUT'].includes(call[1]?.method || 'GET'))).toBe(false)
})

test('keyword workspace mounts once and retains entered seed across navigation', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({ configured: false, runs: [] }))
  click('키워드 발굴')
  await screen.findByText('검색 API 미연결 · 실제 검색은 아직 실행할 수 없습니다.')
  fireEvent.change(screen.getByLabelText('발굴 시작 키워드'), { target: { value: '입력 중인 검색어' } })
  click('통합 관리')
  expect(screen.queryByRole('button', { name: '네이버·구글 첫 페이지 검색' })).toBeNull()
  click('키워드 발굴')
  expect((screen.getByLabelText('발굴 시작 키워드') as HTMLInputElement).value).toBe('입력 중인 검색어')
  expect(vi.mocked(fetch).mock.calls.filter(call => call[0] === '/api/discovery')).toHaveLength(1)
})

test('preparation summary is unknown until fetched and does not imply generated articles', async () => {
  await signedIn()
  expect(screen.getByText('미조회')).toBeTruthy()
  vi.mocked(fetch).mockResolvedValueOnce(json({ preparations: [{ id:'prep',keyword:'준비 키워드',slot:'A-1',siteUrl:'https://example.com',eligible:false,articleGenerated:false }] }))
  click('작성 준비 목록 불러오기')
  await screen.findByText('준비 키워드', { exact: true })
  expect(screen.getByText('재검증·사이트 확인 필요')).toBeTruthy()
  expect(screen.queryByText('미조회')).toBeNull()
})

test('collapsed and mobile navigation retain accessible names and close after selection', async () => {
  await signedIn()
  click('메뉴 접기')
  expect(screen.getByRole('button', { name: '통합 관리', exact: true }).getAttribute('aria-current')).toBe('page')
  click('모바일 메뉴 열기')
  expect(screen.getByRole('button', { name: '모바일 메뉴 닫기' }).getAttribute('aria-expanded')).toBe('true')
  click('PBN 세팅')
  expect(screen.getByRole('button', { name: '모바일 메뉴 열기' }).getAttribute('aria-expanded')).toBe('false')
  expect(screen.getByRole('button', { name: 'PBN 세팅', exact: true }).getAttribute('aria-current')).toBe('page')
})

test('keyword bank preparation records appear in dashboard without a duplicate preparation section', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({ configured:false,runs:[] }))
  click('키워드 발굴')
  await screen.findByText('검색 API 미연결 · 실제 검색은 아직 실행할 수 없습니다.')
  vi.mocked(fetch).mockResolvedValueOnce(json({ keywords:[],nextOffset:null })).mockResolvedValueOnce(json({ preparations:[{id:'linked',keyword:'연결한 준비 키워드',slot:'A-1',siteUrl:'https://example.com',eligible:true,articleGenerated:false}] }))
  click('키워드 DB·작성 준비 불러오기')
  await screen.findByText('서버의 키워드·원본 글 작성 준비 기록을 불러왔습니다.')
  expect(screen.queryByRole('heading',{name:'통합 관리 · 원본 글 작성 준비'})).toBeNull()
  click('통합 관리')
  expect(screen.getByText('연결한 준비 키워드')).toBeTruthy()
  expect(screen.getByText('키워드 발굴에서 조회한 최신 작성 준비 기록입니다.')).toBeTruthy()
  expect(screen.getByText('작성 준비',{exact:true})).toBeTruthy()
})

test('activity recovery navigation opens search workspace without executing searches', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({checkedAt:'2026-11-14T00:00:00Z',scope:'latest_20_per_source',hasEarlierRecords:false,incompleteSources:[],counts:{records:1,attention:1,review:0},items:[{id:'s',source:'search',sourceId:'r',stage:2,at:'2026-11-14T00:00:00Z',title:'재확인할 키워드',label:'검색 확인 미완료',state:'attention',message:'확인 필요',target:'discovery'}]}))
  click('진행 기록 불러오기')
  await screen.findByText('재확인할 키워드')
  vi.mocked(fetch).mockResolvedValueOnce(json({configured:false,runs:[]}))
  click('해당 단계 열기')
  await screen.findByText('검색 API 미연결 · 실제 검색은 아직 실행할 수 없습니다.')
  expect(screen.getByRole('button',{name:'키워드 발굴',exact:true}).getAttribute('aria-current')).toBe('page')
  expect(vi.mocked(fetch).mock.calls.some(call => ['POST','PUT'].includes(call[1]?.method || 'GET'))).toBe(false)
})
