import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Dot, RunBars, Stat, StoryRow, Tabs } from '../components'
import { DAY, ago, every, newInRun, nextRunIn, runCounts, runErrors, score, tone, within } from '../format'
import { useLoad, useNow, usePoll, useToast } from '../hooks'
import type { Draft } from '../draft'
import { TopicForm } from '../TopicForm'
import type { Run, Segment, Story } from '../types'

type Tab = 'stories' | 'runs' | 'setup'

const STATUS_COLOR = { success: 'var(--ok)', partial: 'var(--warn-text)', failed: 'var(--bad)', running: 'var(--accent)' }

export default function Topic() {
  const id = Number(useParams().id)
  const now = useNow()
  const toast = useToast()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'stories'
  const [showDismissed, setShowDismissed] = useState(false)
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const seg = useLoad(() => api.segment(id), [id])
  const runs = useLoad(() => api.runs({ segmentId: id, limit: 100 }), [id])
  const stories = useLoad(() => api.stories(id, { sinceHours: 720, includeDismissed: showDismissed }), [id, showDismissed])

  const reloadAll = () => { seg.reload(); runs.reload(); stories.reload() }
  usePoll(reloadAll)

  async function runNow() {
    setRunning(true)
    try {
      const res = await api.runNow(id)
      if (res.mode === 'github') toast('Dispatched to GitHub Actions. Results show up in a minute or two.')
      else toast(`Run #${res.run.id} ${res.run.status}: ${res.run.fetched} fetched, ${res.run.new_stories} new, ${res.run.updated_stories} updated`,
        res.run.status === 'failed')
    } catch (e) {
      toast(`Run failed: ${e instanceof Error ? e.message : e}`, true)
    } finally {
      setRunning(false)
      reloadAll()
    }
  }

  // "Save & run now" on the home page lands here with state.runNow.
  const started = useRef(false)
  useEffect(() => {
    if ((location.state as { runNow?: boolean } | null)?.runNow && !started.current) {
      started.current = true
      navigate('.', { replace: true, state: null })
      runNow()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function act(label: string, fn: () => Promise<string>) {
    setBusy(label)
    try {
      toast(await fn())
      reloadAll()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(null)
    }
  }

  const segment = seg.data
  if (seg.error) return <div className="empty">{seg.error} · <Link to="/">back to topics</Link></div>
  if (!segment) return <div className="empty">Loading…</div>

  const runList = runs.data ?? []
  const storyList = stories.data ?? []
  const last = runList[0] ?? segment.last_run
  const visible = storyList.filter(s => !s.dismissed)
  const top = visible.reduce<Story | null>((best, s) =>
    (s.scores.combined ?? -1) > (best?.scores.combined ?? -1) ? s : best, null)
  const week = runList.filter(r => within(r.started_at, 7 * DAY, now))
  const wc = runCounts(week)
  const next = nextRunIn(segment, now)
  const setTab = (t: Tab, extra: Record<string, string> = {}) => setParams({ tab: t, ...extra })

  return (
    <>
      <div className="crumb"><Link to="/">Topics</Link> / {segment.name}</div>
      <div className="head">
        <div>
          <h1><Dot t={running ? 'busy' : tone(last, segment.active)} />{segment.name}</h1>
          <div className="sub">
            {segment.definition.summary} · every {every(segment.interval_minutes)} · {next ? `next run ${next}` : 'paused'}
          </div>
        </div>
        <div className="actions">
          <button className="btn" disabled={!!busy} onClick={() => act('pause', async () => {
            await api.updateSegment(id, { active: !segment.active })
            return segment.active ? 'Paused' : 'Resumed'
          })}>{segment.active ? 'Pause' : 'Resume'}</button>
          <button className="btn" disabled={!!busy || running} title="Re-rate stories from the last 48h that were scored on an older definition"
            onClick={() => act('rescore', async () => {
              const r = await api.rescore(id)
              return `Rescored ${r.rescored} stor${r.rescored === 1 ? 'y' : 'ies'}${r.remaining ? `, ${r.remaining} left (token budget)` : ''}`
            })}>{busy === 'rescore' ? 'Rescoring…' : 'Rescore'}</button>
          <button className="btn primary" disabled={running} onClick={runNow}>{running ? 'Running…' : 'Run now'}</button>
        </div>
      </div>

      <Tabs<Tab> value={tab} onChange={t => setTab(t)} tabs={[
        ['stories', `Stories ${visible.length}`], ['runs', `Runs ${runList.length}`], ['setup', 'Setup'],
      ]} />

      <div className="stats">
        <Stat label="Stories · 24h" value={visible.filter(s => within(s.first_seen, DAY, now)).length}
          note={last ? `${last.new_stories} from last run` : 'no runs yet'} />
        <Stat label="Top score" value={<span className="mono">{score(top?.scores.combined ?? null)}</span>} note={top?.headline} />
        <Stat label="Last run" value={last ? last.status : '–'} color={last ? STATUS_COLOR[last.status] : undefined}
          note={last && <span className="mono">{ago(last.started_at, now)} · {last.fetched} fetched · {last.new_stories} new · {last.updated_stories} upd</span>} />
        <Stat label="Runs · 7d" value={<span className="mono">{week.length}</span>}
          note={<span className="mono">{wc.success} ok · {wc.partial} partial · {wc.failed} failed</span>} />
      </div>

      {running && <div className="banner info"><span><Dot t="busy" />Running a scan. This can take a minute while sources are fetched and stories are scored.</span></div>}
      {last && last.errors.length > 0 && (
        <div className="banner bad">
          <span><Dot t="bad" /><span className="mono">{runErrors(last)}</span> on the last run{last.status === 'partial' && '. The other sources ran fine.'}</span>
          {tab !== 'runs' && <a href="#" onClick={e => { e.preventDefault(); setTab('runs') }}>View runs</a>}
        </div>
      )}

      {tab === 'stories' && (
        <StoriesTab stories={storyList} runs={runList} runFilter={params.get('run')} loading={!stories.data && !stories.error}
          error={stories.error} showDismissed={showDismissed} setShowDismissed={setShowDismissed}
          setRunFilter={run => setParams(run ? { tab: 'stories', run } : { tab: 'stories' })}
          onUpdate={s => stories.setData(storyList.map(x => (x.id === s.id ? s : x)))} />
      )}
      {tab === 'runs' && <RunsTab runs={runList} now={now} onPick={r => setTab('stories', { run: String(r.id) })} />}
      {/* keyed so the form takes the server's copy after a save (or a pause from the header) */}
      {tab === 'setup' && <SetupTab key={segment.updated_at} segment={segment} onSaved={reloadAll} onDeleted={() => navigate('/')} />}
    </>
  )
}

function StoriesTab({ stories, runs, runFilter, setRunFilter, showDismissed, setShowDismissed, onUpdate, loading, error }: {
  stories: Story[]; runs: Run[]; runFilter: string | null; setRunFilter: (r: string | null) => void
  showDismissed: boolean; setShowDismissed: (b: boolean) => void; onUpdate: (s: Story) => void
  loading: boolean; error: string | null
}) {
  const toast = useToast()
  const [sort, setSort] = useState<'score' | 'newest'>('score')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [limit, setLimit] = useState(50)

  const run = runFilter ? runs.find(r => String(r.id) === runFilter) : undefined
  let list = run ? newInRun(stories, run) : stories
  if (sort === 'newest') list = [...list].sort((a, b) => Date.parse(b.first_seen) - Date.parse(a.first_seen))

  async function toggle(s: Story) {
    setBusyId(s.id)
    try {
      onUpdate(await (s.dismissed ? api.undismiss(s.id) : api.dismiss(s.id)))
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="toolbar">
        <select className="mono" value={runFilter ?? ''} onChange={e => setRunFilter(e.target.value || null)}>
          <option value="">All stories · last 30 days</option>
          {runs.map(r => (
            <option key={r.id} value={r.id}>New in run #{r.id} · {ago(r.started_at)} · {r.status} · {r.new_stories} new</option>
          ))}
        </select>
        <select value={sort} onChange={e => setSort(e.target.value as 'score' | 'newest')}>
          <option value="score">Sort: score</option>
          <option value="newest">Sort: newest</option>
        </select>
        <span className="grow" />
        <label className="check tiny"><input type="checkbox" checked={showDismissed} onChange={e => setShowDismissed(e.target.checked)} />show dismissed</label>
      </div>
      {error && <div className="empty">Couldn't load stories: {error}</div>}
      {loading && <div className="empty">Loading…</div>}
      {!loading && !error && list.length === 0 && (
        <div className="empty">{run ? 'This run found no new stories.' : 'No stories yet. Hit "Run now" to scan.'}</div>
      )}
      {list.slice(0, limit).map(s => <StoryRow key={s.id} story={s} busy={busyId === s.id} onToggle={() => toggle(s)} />)}
      {list.length > 0 && (
        <div className="foot">
          Showing {Math.min(limit, list.length)} of {list.length}
          {list.length > limit && <> · <button className="btn link tiny" onClick={() => setLimit(limit + 50)}>show more</button></>}
          {run && run.updated_stories > 0 && ` · this run also added coverage to ${run.updated_stories} existing stor${run.updated_stories === 1 ? 'y' : 'ies'}`}
        </div>
      )}
    </>
  )
}

function RunsTab({ runs, now, onPick }: { runs: Run[]; now: number; onPick: (r: Run) => void }) {
  if (runs.length === 0) return <div className="empty">No runs yet.</div>
  return (
    <>
      <div className="toolbar"><span className="tiny">Last {Math.min(30, runs.length)} run{runs.length === 1 ? '' : 's'}</span><span className="grow" /><RunBars runs={runs} /></div>
      <table className="list">
        <thead>
          <tr><th>Run</th><th>Status</th><th className="r">Fetched</th><th className="r">New</th><th className="r hide-sm">Updated</th><th className="r hide-sm">Scored</th><th>Errors</th></tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr key={r.id} className="click" onClick={() => onPick(r)} title="See the stories this run found">
              <td className="mono">#{r.id} · {ago(r.started_at, now)}</td>
              <td><Dot t={tone(r)} />{r.status}</td>
              <td className="r mono">{r.fetched}</td>
              <td className="r mono">{r.new_stories}</td>
              <td className="r mono hide-sm">{r.updated_stories}</td>
              <td className="r mono hide-sm">{r.scored}</td>
              <td className="mono tiny err">{runErrors(r) || <span className="tiny">–</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="foot">Click a run to see the stories it found.</div>
    </>
  )
}

const toDraft = (s: Segment): Draft => ({
  name: s.name, examples: s.examples, note: s.note, definition: s.definition, scoring: s.scoring,
  interval_minutes: s.interval_minutes, active: s.active,
})

function SetupTab({ segment, onSaved, onDeleted }: { segment: Segment; onSaved: () => void; onDeleted: () => void }) {
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(() => toDraft(segment))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(segment))

  async function save() {
    if (!draft.definition) return
    setSaving(true)
    setError(null)
    try {
      await api.updateSegment(segment.id, { ...draft, name: draft.name.trim(), definition: draft.definition })
      toast('Saved')
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${segment.name}" and all its stories and runs?`)) return
    try {
      await api.deleteSegment(segment.id)
      toast(`Deleted ${segment.name}`)
      onDeleted()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), true)
    }
  }

  return (
    <div className="setup">
      <TopicForm value={draft} onChange={setDraft} isNew={false} error={error}
        onDraft={d => api.reanalyze(segment.id, d.examples, d.note).then(r => r.definition)}>
        <span className="tiny" style={{ marginRight: 'auto' }}>
          Definition v{segment.definition_version}. Changing it bumps the version; use Rescore to re-rate recent stories.
        </span>
        <button className="btn danger" onClick={remove}>Delete topic</button>
        <button className="btn" disabled={!dirty || saving} onClick={() => setDraft(toDraft(segment))}>Reset</button>
        <button className="btn primary" disabled={!dirty || saving || !draft.definition || draft.examples.length === 0} onClick={save}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </TopicForm>
    </div>
  )
}
