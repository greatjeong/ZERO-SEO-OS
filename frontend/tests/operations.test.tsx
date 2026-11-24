import {test,expect,vi,afterEach} from 'vitest'
import {render,screen,fireEvent,cleanup} from '@testing-library/react'
import CentralOperations from '../src/CentralOperations'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
const snapshot=()=>({config:{revision:0,data:{aiProvider:'',aiModel:'',volumeProvider:'',notes:'',maxOutputChars:50000}},jobs:[],links:[],documents:[],keywords:[],connections:{ai:false,volume:false,publishing:false,networkExecution:false}})
test('network save failure retains candidate across navigation without making external execution claims',async()=>{
 const api=vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error('저장 충돌'));const dirty=vi.fn()
 const props={api,onDirtyChange:dirty};const r=render(<CentralOperations view="pbn" {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'작업 관리 불러오기'}));await screen.findByText('서버의 작업 관리 기록을 불러왔습니다.')
 fireEvent.change(screen.getByLabelText('관리 원본 글 URL'),{target:{value:'https://example.com/post'}})
 fireEvent.change(screen.getByLabelText('관리 대상 URL'),{target:{value:'https://pbn.example.com'}})
 fireEvent.change(screen.getByLabelText('후보 메모'),{target:{value:'보존할 후보'}})
 fireEvent.click(screen.getByRole('button',{name:'후보·연결 저장'}));await screen.findByText('저장 충돌')
 expect((screen.getByLabelText('후보 메모') as HTMLTextAreaElement).value).toBe('보존할 후보');expect(dirty).toHaveBeenLastCalledWith(true)
 r.rerender(<CentralOperations view="backlinks" {...props}/>);expect((screen.getByLabelText('관리 원본 글 URL') as HTMLInputElement).value).toBe('');r.rerender(<CentralOperations view="pbn" {...props}/>);
 expect((screen.getByLabelText('관리 원본 글 URL') as HTMLInputElement).value).toBe('https://example.com/post')
 expect(api.mock.calls[1][0]).toBe('workbench/network')
})
test('provider settings require readback and retain input on mismatch',async()=>{
 const api=vi.fn().mockResolvedValueOnce(snapshot()).mockResolvedValueOnce({revision:1}).mockResolvedValueOnce(snapshot())
 render(<CentralOperations view="writing" api={api} onDirtyChange={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'작업 관리 불러오기'}));await screen.findByText('서버의 작업 관리 기록을 불러왔습니다.')
 fireEvent.click(screen.getByText('AI·검색량 연결 준비 설정'));fireEvent.change(screen.getByLabelText('AI 모델 이름'),{target:{value:'모델 선택 예정'}})
 fireEvent.click(screen.getByRole('button',{name:'연결 준비 설정 저장'}));await screen.findByText('설정 재조회 미확인 · 입력 유지')
 expect((screen.getByLabelText('AI 모델 이름') as HTMLInputElement).value).toBe('모델 선택 예정')
 expect(screen.queryByText('연결 준비 설정을 서버에 저장·재조회했습니다. 실제 연결은 켜지지 않았습니다.')).toBeNull()
})
test('archive preview does not restore and cancelled restore never writes',async()=>{
 const state=snapshot();const api=vi.fn().mockResolvedValueOnce(state).mockResolvedValueOnce({basis:'b',details:[{table:'hub_records',add:1,same:0,conflictsKept:0}],note:'기존 행 유지'})
 render(<CentralOperations view="sites" api={api} onDirtyChange={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'작업 관리 불러오기'}));await screen.findByText('서버의 작업 관리 기록을 불러왔습니다.')
 const file=new File(['{}'],'backup.json',{type:'application/json'});Object.defineProperty(file,'text',{value:async()=>'{}'})
 fireEvent.change(screen.getByLabelText('작업 데이터 보관본 가져오기'),{target:{files:[file]}});await screen.findByText('복구 미리보기만 완료했습니다. 서버 데이터는 변경하지 않았습니다.')
 vi.spyOn(window,'confirm').mockReturnValue(false);fireEvent.click(screen.getByRole('button',{name:'미리보기 확인 후 누락 자료 복구'}))
 expect(api.mock.calls.map(c=>c[0])).toEqual(['workbench','workbench/archive/preview'])
})
test('rehearsal results are explicitly synthetic and invoke only the rehearsal endpoint',async()=>{
 const state=snapshot();const api=vi.fn().mockResolvedValueOnce(state).mockResolvedValueOnce({status:'succeeded',result:{stages:[{name:'선별 규칙',evidence:{eligible:true}}],note:'모의 자료'}}).mockResolvedValueOnce(state)
 render(<CentralOperations view="keywords" api={api} onDirtyChange={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'작업 관리 불러오기'}));await screen.findByText('서버의 작업 관리 기록을 불러왔습니다.')
 fireEvent.click(screen.getByText('외부 연결 없는 모의 검증'));fireEvent.click(screen.getByRole('button',{name:'모의 연결 검증 실행'}));await screen.findByText('모의 검증 결과를 기록했습니다. 실제 사이트·API에는 요청하지 않았습니다.')
 expect(api.mock.calls.map(c=>c[0])).toEqual(['workbench','workbench/rehearse','workbench']);expect(screen.getByText('선별 규칙')).toBeTruthy()
})
