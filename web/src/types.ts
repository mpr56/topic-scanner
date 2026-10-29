// Mirrors scanner/schemas.py and scanner/api/schemas.py.

export type SourceType = 'google_news' | 'reddit' | 'hackernews'
export type SourceMode = 'search' | 'feed'
export type BuzzSignal = 'outlets' | 'runs' | 'engagement'

export interface SourceConfig {
  type: SourceType
  mode: SourceMode
  queries: string[]
  subreddits: string[]
  sections: string[]
  region: string
  limit: number
  enabled: boolean
}

export interface SegmentDefinition {
  summary: string
  include: string[]
  exclude: string[]
  sources: SourceConfig[]
}

export interface ScoringConfig {
  weights: { match: number; buzz: number; freshness: number }
  fresh_full_hours: number
  fresh_zero_hours: number
  buzz_signals: BuzzSignal[]
  max_new_stories_per_run: number
}

export type RunStatus = 'running' | 'success' | 'partial' | 'failed'

export interface Run {
  id: number
  segment_id: number
  started_at: string
  finished_at: string | null
  status: RunStatus
  fetched: number
  new_articles: number
  new_stories: number
  updated_stories: number
  scored: number
  errors: { source: string; message: string }[]
}

export interface Segment {
  id: number
  name: string
  examples: string[]
  note: string
  definition: SegmentDefinition
  definition_version: number
  scoring: ScoringConfig
  interval_minutes: number
  active: boolean
  last_run_at: string | null
  created_at: string
  updated_at: string
  last_run: Run | null
}

export interface SegmentInput {
  name: string
  examples: string[]
  note: string
  definition: SegmentDefinition
  scoring: ScoringConfig
  interval_minutes: number
  active: boolean
}

export interface Article {
  id: number
  source: SourceType
  outlet: string
  title: string
  url: string
  published_at: string | null
  engagement: number
}

export interface Story {
  id: number
  segment_id: number
  headline: string
  status: 'pending' | 'scored'
  scores: { match: number | null; buzz: number; freshness: number; combined: number | null }
  reason: string | null
  scored_version: number | null
  published_at: string | null
  first_seen: string
  last_seen: string
  runs_seen: number
  dismissed: boolean
  outlets: string[]
  articles: Article[]
}

export type RunNowResult = { mode: 'inline'; run: Run } | { mode: 'github' }

export interface ActionsFailure {
  run_number: number
  event: string
  conclusion: 'failure' | 'timed_out' | 'startup_failure'
  created_at: string
  html_url: string
  failed_step: string | null
}

export interface ActionsStatus {
  failure: ActionsFailure | null
}
