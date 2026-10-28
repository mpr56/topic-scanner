import type { Run, RunNowResult, Segment, SegmentDefinition, SegmentInput, Story } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Fired on any 401 so the app can show the login screen. */
export const UNAUTHORIZED_EVENT = 'ts:unauthorized'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    ...init,
    headers: init.body ? { 'Content-Type': 'application/json', ...init.headers } : init.headers,
  })
  if (res.status === 401 && path !== '/login') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    // FastAPI validation errors: [{loc, msg}, ...]
    if (Array.isArray(body.detail))
      return body.detail.map((d: { loc?: unknown[]; msg: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('; ')
  } catch {
    // not JSON
  }
  return `${res.status} ${res.statusText}`
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  login: (password: string) => post<void>('/login', { password }),
  logout: () => post<void>('/logout'),

  segments: () => request<Segment[]>('/segments'),
  segment: (id: number) => request<Segment>(`/segments/${id}`),
  createSegment: (body: SegmentInput) => post<Segment>('/segments', body),
  updateSegment: (id: number, body: Partial<SegmentInput>) =>
    request<Segment>(`/segments/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSegment: (id: number) => request<void>(`/segments/${id}`, { method: 'DELETE' }),
  analyze: (name: string, examples: string[], note: string) =>
    post<{ definition: SegmentDefinition }>('/segments/analyze', { name, examples, note }),
  reanalyze: (id: number, examples: string[], note: string) =>
    post<{ definition: SegmentDefinition }>(`/segments/${id}/analyze`, { examples, note }),

  stories: (segmentId: number, opts: { sinceHours?: number; includeDismissed?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams({
      since_hours: String(opts.sinceHours ?? 168),
      include_dismissed: String(opts.includeDismissed ?? false),
      limit: String(opts.limit ?? 500),
    })
    return request<Story[]>(`/segments/${segmentId}/stories?${q}`)
  },
  dismiss: (storyId: number) => post<Story>(`/stories/${storyId}/dismiss`),
  undismiss: (storyId: number) => post<Story>(`/stories/${storyId}/undismiss`),
  rescore: (segmentId: number, hours = 48) =>
    post<{ rescored: number; remaining: number }>(`/segments/${segmentId}/rescore?hours=${hours}`),

  runs: (opts: { segmentId?: number; limit?: number } = {}) => {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 100) })
    if (opts.segmentId !== undefined) q.set('segment_id', String(opts.segmentId))
    return request<Run[]>(`/runs?${q}`)
  },
  runNow: (segmentId: number) => post<RunNowResult>(`/segments/${segmentId}/run`),
}
