import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Dot, RunBars, Stat, Tabs } from '../components'
import { DAY, ago, dueAt, every, nextRunIn, runCounts, runErrors, tone, within } from '../format'
import { useLoad, useNow, usePoll, useToast } from '../hooks'
import { emptyDraft, type Draft } from '../draft'
import { TopicForm } from '../TopicForm'
import type { Run, Segment } from '../types'

type Filter = 'all' | 'active' | 'paused'

async function loadAll(): Promise<{ segments: Segment[]; runs: Record<number, Run[]> }> {
  const segments = await api.segments()
  const lists = await Promise.all(segments.map(s => api.runs({ segmentId: s.id, limit: 30 })))
  return { segments, runs: Object.fromEntries(segments.map((s, i) => [s.id, lists[i]])) }
}

export default function Topics() {
  const now = useNow()
  const toast = useToast()
  const navigate = useNavigate()
  const { data, error, reload } = useLoad(loadAll, [])
  usePoll(reload)
  const [filter, setFilter] = useState<Filter>('all')
  const [adding, setAdding] = useState(false)
  const [runningAll, setRunningAll] = useState<string | null>(null)

  if (error) return <div className="empty">Couldn't load topics: {error}</div>
  if (!data) return <div className="empty">Loading…</div>

  const { segments, runs } = data
  const active = segments.filter(s => s.active)
  const shown = filter === 'all' ? segments : filter === 'active' ? active : segments.filter(s => !s.active)
  const recent = Object.values(runs).flat().filter(r => within(r.started_at, DAY, now))
  const counts = runCounts(recent)
  const lastRun = segments.map(s => s.last_run_at).filter((t): t is string => !!t).sort().at(-1) ?? null
  const failing = active.filter(s => s.last_run && s.last_run.errors.length > 0)
  const withErrors = recent.filter(r => r.errors.length > 0).length
  const soonest = [...active].sort((a, b) => dueAt(a) - dueAt(b))[0]

  async function runAll() {
    for (const [i, s] of active.entries()) {
      setRunningAll(`${i + 1}/${active.length} · ${s.name}`)
      try {
        await api.runNow(s.id)
      } catch (e) {
        toast(`${s.name}: ${e instanceof Error ? e.message : e}`, true)
      }
    }
    setRunningAll(null)
    toast(`Ran ${active.length} topic${active.length === 1 ? '' : 's'}`)
    reload()
  }

  return (
    <>
      <div className="head">
        <div>
          <h1>Topics</h1>
          <div className="sub">
            {active.length} active · {segments.length - active.length} paused
            {withErrors > 0 && ` · ${withErrors} run${withErrors === 1 ? '' : 's'} with errors today`}
          </div>
        </div>
        <div className="actions">
          <button className="btn" disabled={!!runningAll || active.length === 0} onClick={runAll}>
            {runningAll ? `Running ${runningAll}…` : 'Run all now'}
          </button>
          <button className="btn primary" onClick={() => setAdding(!adding)}>+ New topic</button>
        </div>
      </div>

      <Tabs<Filter> value={filter} onChange={setFilter} tabs={[
        ['all', `All ${segments.length}`], ['active', `Active ${active.length}`], ['paused', `Paused ${segments.length - active.length}`],
      ]} />

      <div className="stats">
        <Stat label="Topics" value={segments.length} note={`${active.length} active`} />
        <Stat label="New stories · 24h" value={recent.reduce((n, r) => n + r.new_stories, 0)}
          note={`${recent.reduce((n, r) => n + r.updated_stories, 0)} updated`} />
        <Stat label="Runs · 24h" value={recent.length}
          note={<span className="mono">{counts.success} ok · {counts.partial} partial · {counts.failed} failed</span>} />
        <Stat label="Last run" value={<span className="mono">{lastRun ? ago(lastRun, now) : '–'}</span>}
          note={`${recent.reduce((n, r) => n + r.fetched, 0)} articles fetched today`} />
      </div>

      {failing.map(s => (
        <div key={s.id} className="banner bad">
          <span><Dot t="bad" /><b>{s.name}</b> <span className="mono">{runErrors(s.last_run!)}</span> · {ago(s.last_run!.started_at, now)}</span>
          <Link to={`/topics/${s.id}?tab=runs`}>View runs</Link>
        </div>
      ))}

      {adding && <NewTopic onCancel={() => setAdding(false)} onCreated={(id, runNow) => navigate(`/topics/${id}`, { state: { runNow } })} />}

      {segments.length === 0 && !adding ? (
        <div className="empty">No topics yet. <button className="btn link" onClick={() => setAdding(true)}>Add one</button></div>
      ) : (
        <table className="list">
          <thead>
            <tr><th style={{ width: '45%' }}>Topic · sources</th><th className="r">Every</th><th className="r">Last run</th><th className="r hide-sm">New</th><th className="r hide-sm">Last 30 runs</th></tr>
          </thead>
          <tbody>
            {shown.map(s => (
              <tr key={s.id} className={`click${s.active ? '' : ' dim'}`} onClick={() => navigate(`/topics/${s.id}`)}>
                <td>
                  <Dot t={tone(s.last_run, s.active)} /><span className="name">{s.name}</span>
                  {!s.active && <span className="tiny"> paused</span>}
                  <div className="tiny mono sources">{[...new Set(s.definition.sources.filter(c => c.enabled).map(c => c.type))].join(' · ') || 'no sources'}</div>
                </td>
                <td className="r mono">{every(s.interval_minutes)}</td>
                <td className="r mono">{ago(s.last_run_at, now)}</td>
                <td className="r mono hide-sm">{s.last_run ? s.last_run.new_stories : '–'}</td>
                <td className="hide-sm"><RunBars runs={runs[s.id] ?? []} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="foot">
        {segments.length} topic{segments.length === 1 ? '' : 's'}
        {soonest && ` · next run ${nextRunIn(soonest, now)}`}
        {' · '}cron checks hourly
      </div>
    </>
  )
}

function NewTopic({ onCancel, onCreated }: { onCancel: () => void; onCreated: (id: number, runNow: boolean) => void }) {
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(runNow: boolean) {
    if (!draft.definition) return
    setSaving(true)
    setError(null)
    try {
      const seg = await api.createSegment({ ...draft, name: draft.name.trim(), definition: draft.definition })
      onCreated(seg.id, runNow)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  const ready = !!draft.definition && draft.name.trim() !== '' && draft.examples.length > 0
  return (
    <div className="card">
      <h3>New topic</h3>
      <TopicForm value={draft} onChange={setDraft} isNew error={error}
        onDraft={d => api.analyze(d.name.trim(), d.examples, d.note).then(r => r.definition)}>
        {!ready && draft.definition && draft.examples.length === 0 && <span className="tiny">Add at least one example to save.</span>}
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn" disabled={!ready || saving} onClick={() => save(false)}>Save</button>
        <button className="btn primary" disabled={!ready || saving} onClick={() => save(true)}>Save &amp; run now</button>
      </TopicForm>
    </div>
  )
}
