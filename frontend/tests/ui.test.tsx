import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from '../src/App'
import WordPressSites from '../src/WordPressSites'

beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn()); })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole('button', { name }))
const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
function register() {
  fill('사이트 이름', '테스트 사이트'); fill('워드프레스 주소', 'https://example.com'); click('사이트 등록·저장')
}

test('site separation, queue cancel/retry, reload persistence', () => {
  const view = render(<App />)
  fireEvent.change(screen.getByPlaceholderText('예: 워드프레스 SEO 최적화'), { target: { value: '보존 키워드' } })
  click('+ 등록'); click('전체 선택'); click(/선택 키워드 .*작업 대기열에 추가/)
  click('취소'); click('다시 대기')
  expect(screen.getByRole('button', { name: '취소', exact: true })).toBeTruthy()
  click('A-2 사이트'); expect(screen.queryByText('보존 키워드', { exact: true })).toBeNull()
  click('A-1 사이트'); expect(screen.getAllByText('보존 키워드', { exact: true }).length).toBe(2)
  view.unmount(); render(<App />)
  expect(screen.getAllByText('보존 키워드', { exact: true }).length).toBe(2)
})

test('connection rejects mismatched success and resets on remount', async () => {
  const view = render(<WordPressSites site="A-1" />); register()
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ verified: true, site: 'A-2', url: 'https://example.com', checkedAt: new Date().toISOString() })))
  click('실제 연결 확인')
  await screen.findByText(/미연결 ·/)
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ verified: true, site: 'A-1', url: 'https://example.com', checkedAt: new Date().toISOString() })))
  click('실제 연결 확인'); await screen.findByText(/인증 연결 검증 성공/)
  view.unmount(); render(<WordPressSites site="A-1" />)
  expect(screen.getByText('미검증', { exact: true })).toBeTruthy()
})

test('site storage failure never claims registration success', () => {
  render(<WordPressSites site="A-1" />)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('저장 공간 부족') })
  register()
  expect(screen.getByText('저장 공간 부족', { exact: true })).toBeTruthy()
  expect(screen.queryByText(/등록 완료/)).toBeNull()
})

test('server snapshot contains only registration metadata and preserves original browser keys', async () => {
  render(<App />); register()
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ saved: true, id: 1 })))
  click('현재 전체 데이터 서버 보관')
  await screen.findByText(/서버 저장 확인/)
  const payload = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)
  expect(payload.data.version).toBe(2)
  expect(payload.data.sites['A-1']).toEqual({ name: '테스트 사이트', url: 'https://example.com' })
  expect(localStorage.getItem('zero-seo-os-keywords-v1')).toBeNull()
})

test('v1 restore preserves site settings; v2 restores settings and rejects credentials', async () => {
  render(<App />); register()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const upload = (data: unknown) => {
    const file = new File([], 'backup.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: async () => JSON.stringify(data) })
    fireEvent.change(screen.getByLabelText('ZERO SEO OS 백업 JSON 파일'), { target: { files: [file] } })
  }
  const base = { format: 'zero-seo-os-backup', version: 1, keywordsBySite: { 'A-1': ['이전 백업'], 'A-2': [] }, jobs: [] }
  upload(base)
  await screen.findByText('이전 백업', { exact: true })
  expect(screen.getByLabelText('사이트 이름').getAttribute('value')).toBe('테스트 사이트')
  const sites = { 'A-1': { name: '복원 사이트', url: 'https://example.org' }, 'A-2': { name: '', url: '' } }
  upload({ ...base, version: 2, sites })
  await waitFor(() => expect((screen.getByLabelText('사이트 이름') as HTMLInputElement).value).toBe('복원 사이트'))
  upload({ ...base, version: 2, sites: { ...sites, 'A-1': { ...sites['A-1'], password: 'forbidden' } } })
  await screen.findAllByText(/복원 실패:/)
  expect(JSON.parse(localStorage.getItem('zero-seo-os-sites-v1')!)['A-1']).toEqual(sites['A-1'])
})

test('test draft requires explicit confirmation and confirmed draft response', async () => {
  render(<WordPressSites site="A-1" />); register()
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ verified: true, site: 'A-1', url: 'https://example.com', checkedAt: new Date().toISOString(), permissionBasis: 'wordpress-user-capabilities', permissions: { editPosts: true, publishPosts: false } })))
  click('글 작성·발행 권한 확인')
  await screen.findByText(/글 작성 권한: 있음/)
  click('테스트 초안 1개 저장')
  expect(vi.mocked(fetch).mock.calls.length).toBe(1)
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ draftConfirmed: true, site: 'A-1', url: 'https://example.com', status: 'publish', postId: 1, checkedAt: new Date().toISOString() })))
  click('확인하고 초안 저장')
  await screen.findByText(/저장·상태 확인 실패/)
  expect(screen.queryByRole('link', { name: '워드프레스에서 초안 확인' })).toBeNull()
})

test('opening dashboard does not overwrite malformed original browser data', () => {
  localStorage.setItem('zero-seo-os-keywords-v1', '{original-broken-data')
  localStorage.setItem('zero-seo-os-jobs-v1', '{original-jobs')
  render(<App />)
  expect(localStorage.getItem('zero-seo-os-keywords-v1')).toBe('{original-broken-data')
  expect(localStorage.getItem('zero-seo-os-jobs-v1')).toBe('{original-jobs')
})
