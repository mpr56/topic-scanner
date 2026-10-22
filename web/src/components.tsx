import { useState, type ReactNode } from 'react'
import { ago, score, tone, type Tone } from './format'
import type { Run, Story } from './types'

export const Dot = ({ t }: { t: Tone }) => <span className={`dot t-${t}`} />

export function Stat({ label, value, note, color }: { label: string; value: ReactNode; note?: ReactNode; color?: string }) {
  return (
    <div className="stat">
      <div className="lbl">{label}</div>
      <div className="big" style={color ? { color } : undefined}>{value}</div>
      <div className="tiny">{note ?? ' '}</div>
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs">
      {tabs.map(([key, label]) => (
        <button key={key} className={key === value ? 'on' : ''} onClick={() => onChange(key)}>{label}</button>
      ))}
    </div>
  )
}

const BAR_COLORS: Record<Tone, string> = {
  ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)', busy: 'var(--accent)', idle: 'var(--idle)',
}

/** Last `max` runs, oldest on the left; bar height follows articles fetched. */
export function RunBars({ runs, max = 30 }: { runs: Run[]; max?: number }) {
  const shown = runs.slice(0, max).reverse()
  const top = Math.max(1, ...shown.map(r => r.fetched))
  return (
    <div className="bars">
      {shown.map(r => {
        const t = tone(r)
        const h = t === 'bad' ? 18 : 6 + Math.round((r.fetched / top) * 12)
        return (
          <i key={r.id} style={{ height: h, background: BAR_COLORS[t] }}
            title={`#${r.id} · ${r.status} · ${ago(r.started_at)} · ${r.fetched} fetched · ${r.new_stories} new`} />
        )
      })}
    </div>
  )
}

export function StoryRow({ story, onToggle, busy }: { story: Story; onToggle: () => void; busy: boolean }) {
  const [open, setOpen] = useState(false)
  const s = story.scores
  const extra = story.outlets.length - 3
  return (
    <div className={`story${story.dismissed ? ' dismissed' : ''}`}>
      <div className="score">{score(s.combined)}</div>
      <div>
        <b>{story.headline}</b>
        {story.reason && <div className="reason">{story.reason}</div>}
        <div className="chips">
          {story.outlets.slice(0, 3).map(o => <span key={o}>{o}</span>)}
          {extra > 0 && <span>+{extra}</span>}
          <span className="mono">match {score(s.match)} · buzz {score(s.buzz)} · fresh {score(s.freshness)}</span>
          {story.runs_seen > 1 && <span className="mono">seen in {story.runs_seen} runs</span>}
          {story.status === 'pending' && <span className="pending">not scored yet</span>}
        </div>
        <div className="arts">
          <button className="btn link tiny" onClick={() => setOpen(!open)}>
            {open ? '▾' : '▸'} {story.articles.length} article{story.articles.length === 1 ? '' : 's'} · first seen {ago(story.first_seen)}
          </button>
          {open && story.articles.map(a => (
            <div key={a.id}>
              <span className="tiny mono">{a.source}</span> · <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a>{' '}
              <span className="tiny">{a.outlet} · {ago(a.published_at)}{a.engagement > 0 && <span className="mono"> · {a.engagement} pts</span>}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <button className="btn sm" disabled={busy} onClick={onToggle}>{story.dismissed ? 'Restore' : 'Dismiss'}</button>
      </div>
    </div>
  )
}
