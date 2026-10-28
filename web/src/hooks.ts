import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

/** Load data on mount (and whenever deps change); `reload` refetches without clearing what's shown. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true
    load().then(
      d => { if (live) { setData(d); setError(null) } },
      e => { if (live) setError(e instanceof Error ? e.message : String(e)) },
    )
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick(t => t + 1), [])
  return { data, error, reload, setData }
}

export type Toast = (message: string, bad?: boolean) => void
export const ToastContext = createContext<Toast>(() => {})
export const useToast = () => useContext(ToastContext)

/** Call `fn` every `ms` while the tab is visible, so scans started elsewhere (cron, CLI) show up. */
export function usePoll(fn: () => void, ms = 30_000) {
  const ref = useRef(fn)
  useEffect(() => { ref.current = fn })
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) ref.current() }, ms)
    return () => clearInterval(id)
  }, [ms])
}

/** Rerender every `ms` so relative times ("12m ago") stay current. */
export function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}
