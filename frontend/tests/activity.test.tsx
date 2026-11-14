import { afterEach, test, expect, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import CentralActivity from '../src/CentralActivity'
afterEach(cleanup)
const item={id:'search:r',source:'search',sourceId:'r',stage:2,at:'2026-11-14T00:00:00Z',title:'카카오택시 분실물 조회',label:'검색 확인 미완료',state:'attention',message:'양쪽 결과를 확인하세요.',target:'discovery'}
const data={checkedAt:'2026-11-14T00:01:00Z',scope:'latest_20_per_source',hasEarlierRecords:false,incompleteSources:[],items:[item],counts:{records:1,attention:1,review:0}}
test('history stays unqueried until requested and opens relevant stage without rerunning',async()=>{
  const api=vi.fn().mockResolvedValue(data),open=vi.fn()
  render(<CentralActivity api={api} onOpen={open}/> )
  expect(api).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'진행 기록 불러오기'}))
  await screen.findByText(item.title)
  fireEvent.click(screen.getByRole('button',{name:'해당 단계 열기'}))
  expect(open).toHaveBeenCalledWith('discovery',item.title)
  expect(api).toHaveBeenCalledExactlyOnceWith('activity')
})
test('failed refresh preserves old records and does not claim refreshed success',async()=>{
  const api=vi.fn().mockResolvedValueOnce(data).mockRejectedValueOnce(new Error('조회 실패'))
  render(<CentralActivity api={api} onOpen={vi.fn()}/> )
  fireEvent.click(screen.getByRole('button',{name:'진행 기록 불러오기'}));await screen.findByText(item.title)
  fireEvent.click(screen.getByRole('button',{name:'진행 기록 불러오기'}));await screen.findByText('조회 실패')
  expect(screen.getByText(item.title)).toBeTruthy()
})
test('partial data warns and filter does not trigger new API calls',async()=>{
  const api=vi.fn().mockResolvedValue({...data,incompleteSources:['rss'],hasEarlierRecords:true})
  render(<CentralActivity api={api} onOpen={vi.fn()}/> )
  fireEvent.click(screen.getByRole('button',{name:'진행 기록 불러오기'}));await screen.findByText('일부 기록을 읽지 못했습니다. 표시된 건수는 전체 결과가 아닙니다.')
  fireEvent.change(screen.getByLabelText('진행 기록 종류'),{target:{value:'rss'}})
  expect(screen.queryByText(item.title)).toBeNull()
  expect(api).toHaveBeenCalledTimes(1)
})
