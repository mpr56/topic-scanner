import { describe, expect, it } from 'vitest'
import { ago, every, newInRun, nextRunIn, runCounts, score, tone } from './format'
import type { Run, Segment, Story } from './types'

const NOW = Date.parse('2026-10-22T12:00:00Z')

const run = (over: Partial<Run> = {}): Run => ({
  id: 1, segment_id: 1, started_at: '2026-10-22T11:00:00Z', finished_at: '2026-10-22T11:00:00Z',
  status: 'success', fetched: 10, new_articles: 5, new_stories: 3, updated_stories: 1, scored: 3, errors: [], ...over,
})

describe('ago', () => {
  it('formats relative times', () => {
    expect(ago('2026-10-22T11:59:40Z', NOW)).toBe('just now')
    expect(ago('2026-10-22T11:48:00Z', NOW)).toBe('12m ago')
    expect(ago('2026-10-22T09:00:00Z', NOW)).toBe('3h ago')
    expect(ago('2026-10-20T12:00:00Z', NOW)).toBe('2d ago')
    expect(ago(null, NOW)).toBe('never')
  })
})

describe('every', () => {
  it('formats run intervals', () => {
    expect(every(120)).toBe('2h')
    expect(every(90)).toBe('1h 30m')
    expect(every(1440)).toBe('24h')
  })
})

describe('nextRunIn', () => {
  const seg = (over: Partial<Segment>) => ({ active: true, interval_minutes: 120, last_run_at: null, ...over }) as Segment
  it('counts down from the last run', () => {
    expect(nextRunIn(seg({ last_run_at: '2026-10-22T11:00:00Z' }), NOW)).toBe('in 1h')
    expect(nextRunIn(seg({ last_run_at: '2026-10-22T10:48:00Z' }), NOW)).toBe('in 48m')
  })
  it('is due when overdue or never run, and null when paused', () => {
    expect(nextRunIn(seg({ last_run_at: '2026-10-22T08:00:00Z' }), NOW)).toBe('due now')
    expect(nextRunIn(seg({}), NOW)).toBe('due now')
    expect(nextRunIn(seg({ active: false }), NOW)).toBeNull()
  })
})

describe('score', () => {
  it('shows one decimal or a dash', () => {
    expect(score(6.14)).toBe('6.1')
    expect(score(10)).toBe('10.0')
    expect(score(null)).toBe('–')
  })
})

describe('tone', () => {
  it('maps run status to a colour', () => {
    expect(tone(run())).toBe('ok')
    expect(tone(run({ status: 'partial' }))).toBe('warn')
    expect(tone(run({ status: 'failed' }))).toBe('bad')
    expect(tone(run({ status: 'running' }))).toBe('busy')
    expect(tone(null)).toBe('idle')
    expect(tone(run(), false)).toBe('idle')
  })
})

describe('runCounts', () => {
  it('tallies statuses', () => {
    expect(runCounts([run(), run({ status: 'partial' }), run({ status: 'partial' }), run({ status: 'failed' })]))
      .toEqual({ success: 1, partial: 2, failed: 1, running: 0 })
  })
})

describe('newInRun', () => {
  it('picks stories first seen by that run', () => {
    // Runs and stories share the run's timestamp; Postgres and SQLite may differ in precision.
    const stories = [
      { id: 1, first_seen: '2026-10-22T11:00:00.000000Z' },
      { id: 2, first_seen: '2026-10-22T09:00:00Z' },
    ] as Story[]
    expect(newInRun(stories, run()).map(s => s.id)).toEqual([1])
  })
})
