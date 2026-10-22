import { useEffect, useState, type ReactNode } from 'react'
import { manualDefinition, source, type Draft } from './draft'
import type { BuzzSignal, ScoringConfig, SegmentDefinition, SourceConfig, SourceMode, SourceType } from './types'

const SOURCE_TYPES: SourceType[] = ['google_news', 'reddit', 'hackernews']
const SECTIONS = ['WORLD', 'NATION', 'BUSINESS', 'TECHNOLOGY', 'ENTERTAINMENT', 'SPORTS', 'SCIENCE', 'HEALTH']
const INTERVALS = [60, 120, 180, 240, 360, 480, 720, 1440]
const SIGNALS: BuzzSignal[] = ['outlets', 'runs', 'engagement']

/** Text input bound to a list; keeps the raw text so typing separators isn't fought. */
function ListInput({ value, onChange, sep, multiline, placeholder, disabled }: {
  value: string[]; onChange: (v: string[]) => void; sep: ',' | '\n'; multiline?: boolean; placeholder?: string; disabled?: boolean
}) {
  const join = (v: string[]) => v.join(sep === ',' ? ', ' : '\n')
  const parse = (t: string) => t.split(sep).map(s => s.trim()).filter(Boolean)
  const [text, setText] = useState(join(value))
  useEffect(() => {
    if (JSON.stringify(parse(text)) !== JSON.stringify(value)) setText(join(value))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  const change = (t: string) => { setText(t); onChange(parse(t)) }
  return multiline
    ? <textarea value={text} placeholder={placeholder} disabled={disabled} onChange={e => change(e.target.value)} />
    : <input type="text" value={text} placeholder={placeholder} disabled={disabled} onChange={e => change(e.target.value)} />
}

function NumInput({ value, onChange, step = 1, min = 0 }: { value: number; onChange: (n: number) => void; step?: number; min?: number }) {
  return <input type="number" value={value} step={step} min={min}
    onChange={e => { if (e.target.value !== '') onChange(Number(e.target.value)) }} />
}

function SourceRow({ cfg, onChange, onRemove }: { cfg: SourceConfig; onChange: (c: SourceConfig) => void; onRemove: () => void }) {
  const set = (over: Partial<SourceConfig>) => onChange({ ...cfg, ...over })
  let terms: ReactNode
  if (cfg.mode === 'search') {
    terms = <ListInput sep="," value={cfg.queries} onChange={queries => set({ queries })} placeholder="queries, comma separated" />
  } else if (cfg.type === 'reddit') {
    terms = <ListInput sep="," value={cfg.subreddits} onChange={subreddits => set({ subreddits })} placeholder="worldnews, news" />
  } else if (cfg.type === 'google_news') {
    terms = <ListInput sep="," value={cfg.sections} onChange={sections => set({ sections: sections.map(s => s.toUpperCase()) })}
      placeholder="top stories, or sections: WORLD, BUSINESS …" />
  } else {
    terms = <input type="text" value="front page" disabled />
  }
  return (
    <div className={`src${cfg.enabled ? '' : ' off'}`}>
      <label className="check" title="enabled">
        <input type="checkbox" checked={cfg.enabled} onChange={e => set({ enabled: e.target.checked })} />
        <select className="mono" value={cfg.type} onChange={e => set({ type: e.target.value as SourceType })}>
          {SOURCE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <select value={cfg.mode} onChange={e => set({ mode: e.target.value as SourceMode })}>
        <option value="search">search</option>
        <option value="feed">feed</option>
      </select>
      {terms}
      <input type="number" min={1} max={100} value={cfg.limit} title="max items per request"
        onChange={e => { if (e.target.value !== '') set({ limit: Number(e.target.value) }) }} />
      <button className="btn link" title="remove source" onClick={onRemove}>✕</button>
    </div>
  )
}

function DefinitionEditor({ value, onChange }: { value: SegmentDefinition; onChange: (d: SegmentDefinition) => void }) {
  const set = (over: Partial<SegmentDefinition>) => onChange({ ...value, ...over })
  const rows = value.sources
  const setRow = (i: number, cfg: SourceConfig) => set({ sources: rows.map((r, j) => (j === i ? cfg : r)) })
  const unused = SOURCE_TYPES.find(t => !rows.some(r => r.type === t)) ?? 'google_news'
  return (
    <>
      <div className="panel">
        <label className="field">Summary</label>
        <input type="text" value={value.summary} onChange={e => set({ summary: e.target.value })} />
        <div className="grid2" style={{ gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div>
            <label className="field">Include (one per line)</label>
            <ListInput sep={'\n'} multiline value={value.include} onChange={include => set({ include })} />
          </div>
          <div>
            <label className="field">Exclude (one per line)</label>
            <ListInput sep={'\n'} multiline value={value.exclude} onChange={exclude => set({ exclude })} />
          </div>
        </div>
      </div>
      <div className="panel">
        <h4>Sources</h4>
        {rows.length === 0 && <div className="tiny">No sources, so runs will fetch nothing.</div>}
        {rows.map((cfg, i) => (
          <SourceRow key={i} cfg={cfg} onChange={c => setRow(i, c)} onRemove={() => set({ sources: rows.filter((_, j) => j !== i) })} />
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <button className="btn sm" onClick={() => set({ sources: [...rows, source(unused, { queries: [] })] })}>+ Add source</button>
          {rows.some(r => r.type === 'google_news' && r.mode === 'feed') && (
            <span className="tiny">Google sections: {SECTIONS.join(', ')}</span>
          )}
        </div>
      </div>
    </>
  )
}

function ScoringEditor({ value, onChange }: { value: ScoringConfig; onChange: (s: ScoringConfig) => void }) {
  const set = (over: Partial<ScoringConfig>) => onChange({ ...value, ...over })
  const setW = (k: keyof ScoringConfig['weights'], n: number) => set({ weights: { ...value.weights, [k]: n } })
  const toggle = (sig: BuzzSignal, on: boolean) =>
    set({ buzz_signals: on ? SIGNALS.filter(s => s === sig || value.buzz_signals.includes(s)) : value.buzz_signals.filter(s => s !== sig) })
  return (
    <details className="panel">
      <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 12 }}>
        Scoring <span className="tiny mono">match {value.weights.match} · buzz {value.weights.buzz} · fresh {value.weights.freshness}</span>
      </summary>
      <div className="inline-nums" style={{ marginTop: 10 }}>
        <label>Match weight<NumInput step={0.1} value={value.weights.match} onChange={n => setW('match', n)} /></label>
        <label>Buzz weight<NumInput step={0.1} value={value.weights.buzz} onChange={n => setW('buzz', n)} /></label>
        <label>Fresh weight<NumInput step={0.1} value={value.weights.freshness} onChange={n => setW('freshness', n)} /></label>
      </div>
      <div className="inline-nums" style={{ marginTop: 10 }}>
        <label>Fully fresh for (h)<NumInput step={0.5} value={value.fresh_full_hours} onChange={n => set({ fresh_full_hours: n })} /></label>
        <label>Stale after (h)<NumInput value={value.fresh_zero_hours} onChange={n => set({ fresh_zero_hours: n })} /></label>
        <label>Max new / run<NumInput min={1} value={value.max_new_stories_per_run} onChange={n => set({ max_new_stories_per_run: n })} /></label>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <span className="tiny">Buzz from:</span>
        {SIGNALS.map(s => (
          <label key={s} className="check"><input type="checkbox" checked={value.buzz_signals.includes(s)} onChange={e => toggle(s, e.target.checked)} />{s}</label>
        ))}
      </div>
    </details>
  )
}

export function TopicForm({ value, onChange, onDraft, isNew, error, children }: {
  value: Draft
  onChange: (d: Draft) => void
  onDraft: (d: Draft) => Promise<SegmentDefinition>
  isNew: boolean
  error: string | null
  children: ReactNode
}) {
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const set = (over: Partial<Draft>) => onChange({ ...value, ...over })
  const canDraft = value.name.trim() !== '' && value.examples.length > 0

  async function draft() {
    setDrafting(true)
    setDraftError(null)
    try {
      set({ definition: await onDraft(value) })
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : String(e))
    } finally {
      setDrafting(false)
    }
  }

  return (
    <>
      <div className="grid2">
        <div>
          <label className="field">Name</label>
          <input type="text" value={value.name} onChange={e => set({ name: e.target.value })} placeholder="Tesla Roadster" />
          <label className="field">Example headlines (one per line)</label>
          <ListInput sep={'\n'} multiline value={value.examples} onChange={examples => set({ examples })}
            placeholder={'Tesla Roadster production delayed again\nMusk says Roadster demo will "blow your mind"'} />
          <label className="field">Note (optional)</label>
          <input type="text" value={value.note} onChange={e => set({ note: e.target.value })} placeholder="Only the new Roadster, not resale listings" />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" disabled={!canDraft || drafting} onClick={draft}>
              {drafting ? 'Drafting…' : value.definition ? 'Redraft with AI' : 'Draft with AI'}
            </button>
            {!value.definition && (
              <button className="btn link" disabled={!value.name.trim()} onClick={() => set({ definition: manualDefinition(value.name.trim()) })}>
                or write it myself
              </button>
            )}
          </div>
          {draftError && <div className="form-error" style={{ marginTop: 6 }}>{draftError}</div>}
          <label className="field">Run every</label>
          <div className="row">
            <select value={value.interval_minutes} onChange={e => set({ interval_minutes: Number(e.target.value) })}>
              {INTERVALS.map(m => <option key={m} value={m}>{m < 60 ? `${m}m` : `${m / 60}h`}</option>)}
            </select>
            {!isNew && (
              <label className="check" style={{ marginLeft: 8 }}>
                <input type="checkbox" checked={value.active} onChange={e => set({ active: e.target.checked })} />active
              </label>
            )}
          </div>
        </div>
        <div>
          {value.definition
            ? <DefinitionEditor value={value.definition} onChange={definition => set({ definition })} />
            : <div className="panel tiny" style={{ padding: 24, textAlign: 'center' }}>
                Add a name and a few example headlines, then draft with AI. It fills in what to include and exclude and where to look.
              </div>}
          <div style={{ marginTop: 10 }}><ScoringEditor value={value.scoring} onChange={scoring => set({ scoring })} /></div>
        </div>
      </div>
      <div className="form-actions">
        {error && <span className="form-error">{error}</span>}
        {children}
      </div>
    </>
  )
}
