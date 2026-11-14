import { afterEach,test,expect,vi } from 'vitest'
import { render,screen,fireEvent,cleanup,waitFor } from '@testing-library/react'
import CentralAuthoring from '../src/CentralAuthoring'
afterEach(cleanup)
const prep={id:'p',keyword:'카카오택시 분실물 조회',slot:'A-1',siteUrl:'https://example.com',eligible:true,articleGenerated:false}
const doc={id:'p',keyword:prep.keyword,siteUrl:prep.siteUrl,revision:1,status:'research_pending',aiConfigured:false,sourceOptions:[{id:'s',url:'https://one.tistory.com/1',title:'상위 글',platform:'tistory'}],sources:[],outline:[],draft:{title:'',body:''},analysis:null,origin:'not_generated'}
test('AI stays disabled without model configuration and does not fabricate content',async()=>{
  const api=vi.fn().mockResolvedValue(doc)
  render(<CentralAuthoring preparation={prep} api={api} onDirtyChange={vi.fn()}/> )
  await screen.findByText('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.')
  expect((screen.getByRole('button',{name:'AI 원본 글 생성 · 모델 미연결'}) as HTMLButtonElement).disabled).toBe(true)
  expect(api).toHaveBeenCalledExactlyOnceWith('authoring/p/open','POST')
  expect((screen.getByLabelText('원본 글 본문') as HTMLTextAreaElement).value).toBe('')
})
test('failed save retains editing and notifies parent of unsaved content',async()=>{
  const api=vi.fn().mockResolvedValueOnce(doc).mockRejectedValueOnce(new Error('저장 충돌'))
  const dirty=vi.fn()
  render(<CentralAuthoring preparation={prep} api={api} onDirtyChange={dirty}/> )
  await screen.findByText('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.')
  fireEvent.change(screen.getByLabelText('원본 글 본문'),{target:{value:'보존할 원본 본문'}})
  fireEvent.click(screen.getByRole('button',{name:'원본 글 편집 저장'}))
  await screen.findByText('저장 충돌')
  expect((screen.getByLabelText('원본 글 본문') as HTMLTextAreaElement).value).toBe('보존할 원본 본문')
  expect(dirty).toHaveBeenLastCalledWith(true)
})
test('source research only uses selected stored IDs and preserves explicit research status',async()=>{
  const researched={...doc,revision:2,status:'research_ready',sources:[{...doc.sourceOptions[0],status:'collected',headings:['방법']}],outline:['핵심 답변'],analysis:{sourceCount:1,headingCount:1,note:'관찰 결과',observedSignals:{}}}
  const api=vi.fn().mockResolvedValueOnce(doc).mockResolvedValueOnce(researched)
  render(<CentralAuthoring preparation={prep} api={api} onDirtyChange={vi.fn()}/> )
  await screen.findByText('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.')
  fireEvent.click(screen.getByRole('button',{name:'선택한 상위 글 수집·구조 분석'}))
  await screen.findByText('수집 결과와 관찰 패턴을 기록했습니다. 실패한 참고 글은 미확인으로 남깁니다.')
  expect(api).toHaveBeenLastCalledWith('authoring/p/research','POST',{revision:1,sourceIds:['s']})
  expect((screen.getByLabelText('원본 글 목차') as HTMLTextAreaElement).value).toBe('핵심 답변')
})
