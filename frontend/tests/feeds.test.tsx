import { afterEach, test, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import CentralFeeds from '../src/CentralFeeds'
afterEach(cleanup)
test('RSS works independently of search API and preserves unreviewed label', async () => {
  const api = vi.fn().mockResolvedValue({ id:'one',blogUrl:'https://example.com/',feedUrl:'https://example.com/feed/',createdAt:'2026-11-14T00:00:00Z',status:'collected',posts:[{title:'제목',url:'https://example.com/1'}],candidates:[{text:'검토할 글 제목',sources:[{postUrl:'https://example.com/1',sourceType:'post_title'}]}] })
  render(<CentralFeeds api={api} />)
  expect(api).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('RSS를 수집할 블로그 주소'),{target:{value:'https://example.com/'}})
  fireEvent.click(screen.getByRole('button',{name:'RSS 수집 시작'}))
  await screen.findByText('글 1개 · 검토 전 후보 1개 수집·서버 저장 확인')
  expect(screen.getByText('검토할 글 제목')).toBeTruthy()
  expect(screen.getByText('검토 전 후보 · 출처 1개')).toBeTruthy()
  expect(api).toHaveBeenCalledWith('feed-collections','POST',{blogUrl:'https://example.com/'})
})
test('failed refresh preserves existing collection', async () => {
  const api = vi.fn().mockResolvedValueOnce({collections:[{id:'old',blogUrl:'https://example.com/',createdAt:'2026-11-14T00:00:00Z',status:'empty',posts:[],candidates:[]}]}).mockRejectedValueOnce(new Error('연결 오류'))
  render(<CentralFeeds api={api} />)
  fireEvent.click(screen.getByRole('button',{name:'RSS 수집 기록 불러오기'}))
  await screen.findByText('https://example.com/')
  fireEvent.click(screen.getByRole('button',{name:'RSS 수집 기록 불러오기'}))
  await screen.findByText('연결 오류')
  expect(screen.getByText('https://example.com/')).toBeTruthy()
})
