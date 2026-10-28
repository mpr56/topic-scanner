import { useState, type FormEvent } from 'react'
import { api } from '../api'

export default function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(password)
      onLoggedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form onSubmit={submit}>
        <div className="brand"><div className="logo">T</div>Topic Scanner</div>
        <label className="field">Password</label>
        <input type="password" autoFocus value={password} onChange={e => setPassword(e.target.value)} />
        {error && <div className="form-error" style={{ marginTop: 8 }}>{error}</div>}
        <button className="btn primary" style={{ width: '100%', marginTop: 12 }} disabled={busy || !password}>Log in</button>
      </form>
    </div>
  )
}
