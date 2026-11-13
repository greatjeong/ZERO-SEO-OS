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
  expect(fetch).toHaveBeenCalledTimes(3)
})

test('backup import preview cancellation never writes', async () => {
  await signedIn()
  vi.mocked(fetch).mockResolvedValueOnce(json({ baseRevision: 1, data, counts: { 'A-1': 1, 'A-2': 1 }, jobs: 0 }))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  const file = new File([], 'backup.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify({ ...data, version: 1 }) })
  fireEvent.change(screen.getByLabelText('v1/v2 JSON 가져오기'), { target: { files: [file] } })
  await waitFor(() => expect(window.confirm).toHaveBeenCalled())
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(vi.mocked(fetch).mock.calls.at(-1)![0]).toBe('/api/import/preview')
  expect(screen.getByText('기존 키워드', { exact: true })).toBeTruthy()
})

test('missing workspace is not silently initialized', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ authenticated: true, csrf: 'csrf' })).mockResolvedValueOnce(json({ revision: 0, data: null }))
  render(<CentralApp />)
  await screen.findByRole('heading', { name: '서버 작업 공간이 비어 있습니다' })
  expect(fetch).toHaveBeenCalledTimes(2)
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
