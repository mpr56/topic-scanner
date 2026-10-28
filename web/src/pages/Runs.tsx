import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Dot } from '../components'
import { ago, runErrors, tone } from '../format'
import { useLoad, useNow, usePoll } from '../hooks'

export default function Runs() {
  const now = useNow()
  const navigate = useNavigate()
  const { data, error, reload } = useLoad(() => Promise.all([api.runs({ limit: 100 }), api.segments()]), [])
  usePoll(reload)

  if (error) return <div className="empty">Couldn't load runs: {error}</div>
  if (!data) return <div className="empty">Loading…</div>
  const [runs, segments] = data
  const names = Object.fromEntries(segments.map(s => [s.id, s.name]))

  return (
    <>
      <div className="head">
        <div>
          <h1>Runs</h1>
          <div className="sub">The last {runs.length} scans across all topics</div>
        </div>
      </div>
      <div style={{ height: 12, borderBottom: '1px solid var(--line)' }} />
      {runs.length === 0 ? <div className="empty">No runs yet.</div> : (
        <table className="list">
          <thead>
            <tr><th>Run</th><th>Topic</th><th>Status</th><th className="r">Fetched</th><th className="r">New</th><th className="r hide-sm">Updated</th><th>Errors</th></tr>
          </thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.id} className="click" onClick={() => navigate(`/topics/${r.segment_id}?tab=stories&run=${r.id}`)}>
                <td className="mono">#{r.id} · {ago(r.started_at, now)}</td>
                <td>
                  <Link to={`/topics/${r.segment_id}`} onClick={e => e.stopPropagation()}>{names[r.segment_id] ?? `#${r.segment_id}`}</Link>
                </td>
                <td><Dot t={tone(r)} />{r.status}</td>
                <td className="r mono">{r.fetched}</td>
                <td className="r mono">{r.new_stories}</td>
                <td className="r mono hide-sm">{r.updated_stories}</td>
                <td className="mono tiny err">{runErrors(r) || <span className="tiny">–</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
