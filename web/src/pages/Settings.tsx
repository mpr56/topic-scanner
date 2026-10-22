import { api } from '../api'
import { useLoad, useToast } from '../hooks'

export default function Settings({ onLoggedOut }: { onLoggedOut: () => void }) {
  const toast = useToast()
  const health = useLoad(api.health, [])

  async function logout() {
    await api.logout()
    toast('Logged out')
    onLoggedOut()
  }

  return (
    <>
      <div className="head">
        <div>
          <h1>Settings</h1>
          <div className="sub">Most settings live in the backend's <span className="mono">.env</span></div>
        </div>
      </div>
      <div style={{ height: 12, borderBottom: '1px solid var(--line)' }} />
      <table className="list">
        <tbody>
          <tr>
            <td style={{ width: 180 }}>API</td>
            <td className="mono">{health.error ? <span className="err">{health.error}</span> : health.data ? 'ok' : '…'}</td>
          </tr>
          <tr>
            <td>Session</td>
            <td>
              <button className="btn sm" onClick={logout}>Log out</button>{' '}
              <span className="tiny">In local dev the Vite proxy sends API_TOKEN from .env, so you stay signed in anyway.</span>
            </td>
          </tr>
          <tr>
            <td>Reddit</td>
            <td className="tiny">
              Without credentials Reddit returns 403 to most networks, and the run carries on without it.
              Reddit no longer issues new API keys; existing keys go in REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.
            </td>
          </tr>
        </tbody>
      </table>
    </>
  )
}
