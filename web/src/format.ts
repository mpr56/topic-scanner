import type { Run, RunStatus, Segment, Story } from './types'

const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR

function duration(ms: number): string {
  if (ms < HOUR) return `${Math.max(1, Math.round(ms / MIN))}m`
  const h = Math.floor(ms / HOUR)
  const m = Math.round((ms % HOUR) / MIN)
  return m ? `${h}h ${m}m` : `${h}h`
}

export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return 'never'
  const ms = now - Date.parse(iso)
  if (ms < MIN) return 'just now'
  if (ms < HOUR) return `${Math.floor(ms / MIN)}m ago`
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h ago`
  return `${Math.floor(ms / DAY)}d ago`
}

export const every = (minutes: number) => duration(minutes * MIN)

/** Epoch ms when the segment's interval has elapsed (0 if it has never run). */
export const dueAt = (segment: Segment) =>
  segment.last_run_at ? Date.parse(segment.last_run_at) + segment.interval_minutes * MIN : 0

/** When the hourly cron will next pick this segment up (roughly), or null if paused. */
export function nextRunIn(segment: Segment, now = Date.now()): string | null {
  if (!segment.active) return null
  const ms = dueAt(segment) - now
  return ms <= 0 ? 'due now' : `in ${duration(ms)}`
}

export const score = (n: number | null) => (n === null ? '–' : n.toFixed(1))

export type Tone = 'ok' | 'warn' | 'bad' | 'busy' | 'idle'

const TONES: Record<RunStatus, Tone> = { success: 'ok', partial: 'warn', failed: 'bad', running: 'busy' }

export function tone(run: Run | null, active = true): Tone {
  if (!active || !run) return 'idle'
  return TONES[run.status]
}

export function runCounts(runs: Run[]): Record<RunStatus, number> {
  const counts = { success: 0, partial: 0, failed: 0, running: 0 }
  for (const r of runs) counts[r.status]++
  return counts
}

/** Stories a run discovered: the runner stamps both with the same `now`. */
export function newInRun(stories: Story[], run: Run): Story[] {
  const t = Date.parse(run.started_at)
  return stories.filter(s => Date.parse(s.first_seen) === t)
}

export const runErrors = (run: Run) => run.errors.map(e => `${e.source}: ${e.message}`).join(' · ')

export const within = (iso: string, ms: number, now = Date.now()) => now - Date.parse(iso) <= ms

export { HOUR, DAY }
