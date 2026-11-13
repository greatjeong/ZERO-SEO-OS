import { useState } from 'react'

type Props = { slot: string; url: string; disabled: boolean; api: (path: string, method?: string, body?: unknown) => Promise<unknown> }
type Verification = { verified: boolean; url: string; checkedAt: string; permissions: { editPosts: boolean | null; publishPosts: boolean | null } }
export default function CentralWordPress({ slot, url, disabled, api }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('연결 미확인')
  const [result, setResult] = useState<Verification | null>(null)
  async function act(save: boolean) {
    setBusy(true); setResult(null); setMessage(save ? '인증정보 저장 중…' : '실제 인증 확인 중…')
    try {
      if (save) {
        const response = await api(`wordpress/${slot}/credentials`, 'PUT', { username, applicationPassword: password }) as { configured?: boolean }
        if (response.configured !== true) throw new Error('저장 결과 미확인')
        setMessage('암호화 저장 확인 · 실제 연결 확인을 눌러주세요.')
      } else {
        const response = await api(`wordpress/${slot}/verify`, 'POST') as Verification
        if (response.verified !== true || response.url !== url.replace(/\/$/, '') || !response.checkedAt || !response.permissions) throw new Error('연결 결과 미확인')
        setResult(response); setMessage(`인증 연결 검증 성공 · ${new Date(response.checkedAt).toLocaleString()} (확인 시점 기준)`)
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : '연결 결과 미확인') }
    finally { setPassword(''); setBusy(false) }
  }
  const capability = (value: boolean | null) => value === true ? '있음' : value === false ? '없음' : '미확인'
  return <fieldset disabled={disabled || busy} className="central-fields"><legend>워드프레스 연결</legend>
    <p>사이트 정보를 서버에 저장한 뒤 등록하세요. 앱 비밀번호는 서버에서 암호화하며 JSON 백업에 포함하지 않습니다.</p>
    <label>워드프레스 사용자명<input value={username} autoComplete="off" onChange={event => { setUsername(event.target.value); setResult(null); setMessage('연결 미확인') }} /></label>
    <label>앱 비밀번호<input type="password" value={password} autoComplete="new-password" onChange={event => { setPassword(event.target.value); setResult(null); setMessage('연결 미확인') }} /></label>
    <button disabled={!username || !password} onClick={() => void act(true)}>인증정보 암호화 저장</button>
    <button onClick={() => void act(false)}>실제 연결 확인</button>
    <p role="status">{message}</p>
    {result && <p>글 작성 권한: {capability(result.permissions.editPosts)} / 글 발행 권한: {capability(result.permissions.publishPosts)} · 사용자 권한 기준이며 실제 저장·발행 결과와는 별도입니다.</p>}
    <p>이 화면은 연결 확인만 수행합니다. 초안 저장·공개 발행은 실행하지 않습니다.</p>
  </fieldset>
}
