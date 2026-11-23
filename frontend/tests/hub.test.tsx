import {test,expect,vi,afterEach} from 'vitest'
import {render,screen,fireEvent,cleanup} from '@testing-library/react'
import CentralHub from '../src/CentralHub'
import data from '../src/guide-data.json'
afterEach(cleanup)
test('recovered guide catalog retains all 48 unique items',()=>{
 const items=data.stages.flatMap(s=>s.items)
 expect(data.stages).toHaveLength(12);expect(items).toHaveLength(48);expect(new Set(items.map(g=>g.id)).size).toBe(48)
 for(const g of items){expect(g.steps.length).toBeGreaterThan(0);expect(g.verify).toHaveLength(2)}
})
test('guide progress requires server load, failed save retains input, revision sent',async()=>{
 const api=vi.fn().mockResolvedValueOnce({revision:0,data:{},updatedAt:null}).mockRejectedValueOnce(new Error('저장 충돌'))
 const dirty=vi.fn();render(<CentralHub view="guides" api={api} navigate={vi.fn()} onDirty={dirty}/>)
 fireEvent.click(screen.getByRole('button',{name:/도메인 구매 및 등록 확인/}))
 expect((screen.getByLabelText('실습 메모 · 비밀번호를 적지 마세요') as HTMLTextAreaElement).disabled).toBe(true)
 fireEvent.click(screen.getAllByRole('button',{name:'서버 기록 불러오기'})[0]);await screen.findByText('서버 기록을 불러왔습니다.')
 fireEvent.change(screen.getByLabelText('실습 메모 · 비밀번호를 적지 마세요'),{target:{value:'유지할 실습 기록'}})
 fireEvent.click(screen.getAllByRole('button',{name:'기록 서버 저장'})[0]);await screen.findByText(/저장 충돌/)
 expect((screen.getByLabelText('실습 메모 · 비밀번호를 적지 마세요') as HTMLTextAreaElement).value).toBe('유지할 실습 기록')
 expect(api.mock.calls[1][1]).toBe('PUT');expect(api.mock.calls[1][2].revision).toBe(0);expect(dirty).toHaveBeenLastCalledWith(true)
})
test('planning drafts survive navigation and never imply external execution',async()=>{
 const api=vi.fn().mockResolvedValue({revision:0,data:{sites:'',original:'',language:'',interval:'',notes:''}})
 const props={api,navigate:vi.fn(),onDirty:vi.fn()};const r=render(<CentralHub view="pbn" {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'서버 기록 불러오기'}));await screen.findByText('서버 기록을 불러왔습니다.')
 fireEvent.change(screen.getByLabelText('운영 메모'),{target:{value:'보존할 설정'}})
 r.rerender(<CentralHub view="stats" {...props}/>);expect(screen.getByRole('heading',{name:'통계·성과 · 측정 연결 전'})).toBeTruthy()
 r.rerender(<CentralHub view="pbn" {...props}/>);expect((screen.getByLabelText('운영 메모') as HTMLTextAreaElement).value).toBe('보존할 설정')
 expect(api).toHaveBeenCalledTimes(1)
})
