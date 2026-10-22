import type { ScoringConfig, SegmentDefinition, SegmentInput, SourceConfig, SourceType } from './types'

/** A topic being created or edited; `definition` is null until drafted. */
export type Draft = Omit<SegmentInput, 'definition'> & { definition: SegmentDefinition | null }

export const DEFAULT_SCORING: ScoringConfig = {
  weights: { match: 0.5, buzz: 0.3, freshness: 0.2 },
  fresh_full_hours: 2,
  fresh_zero_hours: 48,
  buzz_signals: ['outlets', 'runs', 'engagement'],
  max_new_stories_per_run: 40,
}

export const emptyDraft = (): Draft => ({
  name: '', examples: [], note: '', definition: null, scoring: DEFAULT_SCORING, interval_minutes: 120, active: true,
})

export const source = (type: SourceType, over: Partial<SourceConfig> = {}): SourceConfig => ({
  type, mode: 'search', queries: [], subreddits: [], sections: [], region: 'US', limit: 25, enabled: true, ...over,
})

/** A starting definition when you'd rather not wait on the AI. */
export const manualDefinition = (name: string): SegmentDefinition => ({
  summary: name,
  include: [],
  exclude: [],
  sources: [
    source('google_news', { queries: [name] }),
    source('reddit', { queries: [name], enabled: false }),
    source('hackernews', { queries: [name] }),
  ],
})
