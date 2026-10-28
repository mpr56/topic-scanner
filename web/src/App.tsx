import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { UNAUTHORIZED_EVENT, api } from './api'
import { ActionsBanner } from './components'
import { ago } from './format'
import { ToastContext, useLoad, useNow, usePoll } from './hooks'
import Login from './pages/Login'
import Runs from './pages/Runs'
import Settings from './pages/Settings'
import Topic from './pages/Topic'
import Topics from './pages/Topics'

export default function App() {
  const [authed, setAuthed] = useState(true)
  const [toast, setToast] = useState<{ message: string; bad: boolean } | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const show = useCallback((message: string, bad = false) => {
    setToast({ message, bad })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setToast(null), bad ? 7000 : 4000)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {authed ? <Shell onLoggedOut={() => setAuthed(false)} /> : <Login onLoggedIn={() => setAuthed(true)} />}
      {toast && <div className={`toast${toast.bad ? ' bad' : ''}`} onClick={() => setToast(null)}>{toast.message}</div>}
    </ToastContext.Provider>
  )
}

function Shell({ onLoggedOut }: { onLoggedOut: () => void }) {
  const location = useLocation()
  const now = useNow()
  // Refresh the sidebar on every navigation; it's one small request.
  const { data: segments, error } = useLoad(api.segments, [location.pathname])
  const lastRun = segments?.map(s => s.last_run_at).filter((t): t is string => !!t).sort().at(-1) ?? null
  // GitHub Actions failures that never reached the database, so they don't show up as runs.
  const actions = useLoad(api.actionsStatus, [])
  usePoll(actions.reload, 60_000)
  const failure = actions.data?.failure

  return (
    <div className="shell">
      <div className="frame">
        <nav className="side">
          <div className="brand"><div className="logo">T</div>Topic Scanner</div>
          <div className="nav">
            <NavLink to="/" end className={({ isActive }) => (isActive || location.pathname.startsWith('/topics') ? 'active' : '')}>
              Topics <span>{segments?.length ?? ''}</span>
            </NavLink>
            <NavLink to="/runs">Runs</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </div>
          <div className="side-foot">
            {error ? <span style={{ color: 'var(--bad)' }}>api unreachable</span> : 'api ok'}
            <br />last run {ago(lastRun, now)}
          </div>
        </nav>
        <main className="main">
          {failure && <ActionsBanner failure={failure} now={now} />}
          <Routes>
            <Route path="/" element={<Topics />} />
            <Route path="/topics/:id" element={<Topic />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/settings" element={<Settings onLoggedOut={onLoggedOut} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
