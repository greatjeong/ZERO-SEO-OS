import { afterEach, test, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import CentralKeywordBank from '../src/CentralKeywordBank'
import CentralFeeds from '../src/CentralFeeds'
afterEach(cleanup)
const row = { id:'k',keyword:'카카오택시 분실물 조회',revision:1,status:'pending',sources:[],createdAt:'2026-11-14T00:00:00Z',checkedAt:null,nextCheckAt:null,retryAt:null,verification:'not_checked',latestRunId:null,evidence:null,reviewRequired:true }
const click = (name: string) => fireEvent.click(screen.getByRole('button',{name,exact:true}))
test('unverified keyword cannot be activated or handed off', async () => {
  const api = vi.fn().mockResolvedValueOnce({keywords:[row],nextOffset:null}).mockResolvedValueOnce({preparations:[]})
  render(<CentralKeywordBank api={api} />)
  click('키워드 DB·작성 준비 불러오기')
  await screen.findByText('카카오택시 분실물 조회 · 검토 대기')
  fireEvent.change(screen.getByLabelText('카카오택시 분실물 조회 검토 이유'),{target:{value:'테스트 선택'}})
  expect((screen.getByRole('button',{name:'선택·활성 DB 반영'}) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button',{name:'통합 관리로 연결'}) as HTMLButtonElement).disabled).toBe(true)
})
test('active keyword handoff shows preparation and retains keyword in DB', async () => {
  const active = {...row,status:'active',verification:'both_retrieved',reviewRequired:false,latestRunId:'r'}
  const jobs = [{id:'job',keyword:row.keyword,slot:'A-1',siteUrl:'https://example.com',eligible:true,articleGenerated:false}]
  const api = vi.fn().mockResolvedValueOnce({keywords:[active],nextOffset:null}).mockResolvedValueOnce({preparations:[]}).mockResolvedValueOnce({created:true,preparation:jobs[0]}).mockResolvedValueOnce({preparations:jobs})
  render(<CentralKeywordBank api={api} />)
  click('키워드 DB·작성 준비 불러오기')
  await screen.findByText('서버의 키워드·원본 글 작성 준비 기록을 불러왔습니다.')
  click('통합 관리로 연결')
  await screen.findByText('원본 글 작성 준비')
  expect(screen.getByText('카카오택시 분실물 조회 · 활성')).toBeTruthy()
  expect(api).toHaveBeenCalledWith('keyword-bank/k/handoff','POST',{revision:1,slot:'A-1'})
})
test('failed check does not overwrite loaded state or invent success', async () => {
  const api = vi.fn().mockResolvedValueOnce({keywords:[row],nextOffset:null}).mockResolvedValueOnce({preparations:[]}).mockRejectedValueOnce(new Error('검색 API 미연결'))
  render(<CentralKeywordBank api={api} />)
  click('키워드 DB·작성 준비 불러오기')
  await screen.findByText('서버의 키워드·원본 글 작성 준비 기록을 불러왔습니다.')
  click('네이버·구글 검색·재검증')
  await screen.findByText('검색 API 미연결')
  expect(screen.getByText('카카오택시 분실물 조회 · 검토 대기')).toBeTruthy()
})
test('feed candidates allow editing search phrase while sending original source index', async () => {
  const feed={id:'f',blogUrl:'https://example.com',createdAt:'2026-11-14T00:00:00Z',status:'collected',posts:[{}],candidates:[{text:'카카오택시 분실물 조회 완벽 정리',sources:[{sourceType:'post_title',postUrl:'https://example.com/1'}]}]}
  const api=vi.fn().mockResolvedValueOnce({collections:[feed]}).mockResolvedValueOnce({keywords:[row]})
  render(<CentralFeeds api={api} />)
  click('RSS 수집 기록 불러오기')
  await screen.findByText('카카오택시 분실물 조회 완벽 정리')
  fireEvent.click(screen.getByLabelText('f 후보 1 선택'))
  fireEvent.change(screen.getByLabelText('f 후보 1 검색어'),{target:{value:row.keyword}})
  click('선택 후보를 검토 대기로 보내기')
  await screen.findByText('검토 대기로 보냈습니다. 아래 키워드 DB·작성 준비 불러오기로 확인하세요. 아직 활성 DB 등록은 아닙니다.')
  expect(api).toHaveBeenCalledWith('keyword-bank/stage','POST',{collectionId:'f',selections:[{index:0,keyword:row.keyword}]})
})
