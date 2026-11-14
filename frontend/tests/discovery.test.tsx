import { afterEach, test, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import CentralDiscovery from '../src/CentralDiscovery'
afterEach(cleanup)
test('unconfigured provider disables search and does not invent results', async () => {
  const api = vi.fn().mockResolvedValue({ configured: false, runs: [] })
  render(<CentralDiscovery api={api} />)
  await screen.findByText('검색 API 미연결 · 실제 검색은 아직 실행할 수 없습니다.')
  expect((screen.getByRole('button', { name: '네이버·구글 첫 페이지 검색' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).toHaveBeenCalledTimes(1)
})
test('partial engine result remains incomplete with actual URLs and unknown platform', async () => {
  const run = { id:'r', keyword:'카카오택시 분실물 조회', createdAt:'2026-11-14T00:00:00Z', status:'incomplete', engines:{naver:{status:'retrieved', targetPresence:'unknown', results:[{id:'x',url:'https://example.com/post',blogOrigin:'https://example.com',title:'검색 결과',section:'web_results',sectionPosition:1,platform:'unknown',evidence:'not_inspected'}]},google:{status:'unverified', targetPresence:'unknown', results:[]}} }
  const api = vi.fn().mockResolvedValueOnce({configured:true,runs:[]}).mockResolvedValueOnce(run)
  render(<CentralDiscovery api={api} />)
  await screen.findByText('검색 요청 준비')
  fireEvent.click(screen.getByRole('button',{name:'네이버·구글 첫 페이지 검색'}))
  await screen.findByText('확인 미완료 · 실패를 노출 없음으로 처리하지 않았습니다.')
  expect(screen.getByRole('link',{name:'https://example.com/post'}).getAttribute('href')).toBe('https://example.com/post')
  expect(screen.getByText('구글 · 미확인 · 노출 여부 미확인')).toBeTruthy()
  expect(api).toHaveBeenLastCalledWith('discovery','POST',{keyword:'카카오택시 분실물 조회'})
})
