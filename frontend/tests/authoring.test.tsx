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
test('version compare never overwrites editor and restore failure retains saved document',async()=>{
 const current={...doc,revision:3,draft:{title:'현재 제목',body:'현재 본문'}}
 const old={...doc,revision:2,draft:{title:'이전 제목',body:'이전 본문'}}
 const api=vi.fn().mockResolvedValueOnce(current).mockResolvedValueOnce({versions:[{event:'draft_saved',document:old}]}).mockResolvedValueOnce({currentRevision:3,selectedRevision:2,title:'이전 제목',diff:'-현재 본문\n+이전 본문'}).mockRejectedValueOnce(new Error('복원 충돌'))
 render(<CentralAuthoring preparation={prep} api={api} onDirtyChange={vi.fn()}/>);
 await screen.findByText('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.')
 fireEvent.click(screen.getByRole('button',{name:'원본 글 이전 버전 보기'}));await screen.findByText('이전 저장본을 불러왔습니다. 현재 편집본은 교체하지 않았습니다.')
 fireEvent.click(screen.getByText('버전 2 · draft_saved'));fireEvent.click(screen.getByRole('button',{name:'버전 2 비교·복원 준비'}));await screen.findByText('선택한 이전 버전과 서버 현재 버전을 비교했습니다. 아직 복원하지 않았습니다.')
 expect((screen.getByLabelText('원본 글 본문') as HTMLTextAreaElement).value).toBe('현재 본문')
 vi.spyOn(window,'confirm').mockReturnValue(true);fireEvent.click(screen.getByRole('button',{name:'비교 확인 후 원고 버전 복원'}));await screen.findByText('복원 충돌')
 expect((screen.getByLabelText('원본 글 본문') as HTMLTextAreaElement).value).toBe('현재 본문')
 expect(api).toHaveBeenLastCalledWith('authoring/p/restore','POST',{revision:3,sourceRevision:2});vi.restoreAllMocks()
})

test('WP preview keeps unsaved editor safe and never calls a publish endpoint',async()=>{
 const api=vi.fn().mockResolvedValueOnce(doc).mockResolvedValueOnce({revision:doc.revision,title:doc.draft.title,siteUrl:prep.siteUrl,contentHtml:'<h2>안전 본문</h2>',note:'변환 미리보기'})
 render(<CentralAuthoring preparation={prep} api={api} onDirtyChange={vi.fn()}/>);
 await screen.findByText('원본 글 작업 공간을 불러왔습니다. 참고 글부터 확인하세요.')
 fireEvent.click(screen.getByRole('button',{name:'워드프레스 초안 미리보기'}));await screen.findByText('변환 미리보기')
 expect(screen.getByTitle('워드프레스 초안 본문 미리보기').getAttribute('sandbox')).toBe('')
 expect(api.mock.calls.map(c=>c[0])).toEqual(['authoring/p/open','authoring/p/wordpress-preview'])
 fireEvent.change(screen.getByLabelText('원본 글 본문'),{target:{value:'미저장 편집'}})
 expect((screen.getByRole('button',{name:'워드프레스용 본문 HTML 내보내기'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByLabelText('원본 글 본문') as HTMLTextAreaElement).value).toBe('미저장 편집')
})
