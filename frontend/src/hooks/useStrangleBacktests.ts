import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const BASE = '/api/v1/strangle-backtests'

// ── Types ──────────────────────────────────────────────────────────────────

export interface RunMetrics {
  net: number | null
  profit_factor: number | null
  win_rate: number | null
  max_dd: number | null
  sharpe: number | null
  calmar: number | null
  trades: number
  halted: number
  days: number
}

export interface BacktestRun {
  run_id: string
  kind: 'single' | 'sweep' | 'walkforward'
  strategy_id: string
  config: Record<string, unknown>
  window: { from: string; to: string; biz_days?: number; traded_days?: number }
  metrics: RunMetrics
  verdict: 'PASS' | 'REVIEW' | null
  promotion_state: 'none' | 'promoted'
  git_sha: string | null
  created_at: string
  stitched_oos?: Record<string, unknown>
}

export interface EquityPoint {
  date: string
  net: number | null
  cum_equity: number | null
  peak: number | null
  drawdown: number | null
}

export interface DayRow {
  date: string
  expiry: string
  nifty_open: number | null
  nifty_close: number | null
  trades: number
  gross_pnl: number | null
  commission: number | null
  net: number | null
  cum_equity: number | null
  drawdown: number | null
  halted: string
  build_ms: number | null
  sim_ms: number | null
}

export interface FoldDoc {
  fold_index: number
  is_window: { start: string; end: string }
  oos_window: { start: string; end: string }
  pick_label: string
  is_metrics: { net: number | null; profit_factor: number | null; sharpe: number | null }
  oos_metrics: {
    net: number | null; profit_factor: number | null; win_rate: number | null
    sharpe: number | null; max_dd: number | null; days: number; trades: number
  }
}

export interface Fill {
  time: string
  side: string
  opt_type: string
  strike: number | null
  qty: number
  price: number | null
  nifty: number | null
  leg_pnl: number | null
  day_pnl: number | null
  commission: number | null
  note: string
}

// ── API fetchers ─────────────────────────────────────────────────────────────

async function apiFetch<T>(url: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export interface ListRunsParams {
  kind?: string
  strategy_id?: string
  verdict?: string
  sort_by?: string
  sort_dir?: number
  limit?: number
  offset?: number
}

export function useRunsList(params: ListRunsParams = {}) {
  const qs = new URLSearchParams()
  if (params.kind) qs.set('kind', params.kind)
  if (params.strategy_id) qs.set('strategy_id', params.strategy_id)
  if (params.verdict) qs.set('verdict', params.verdict)
  if (params.sort_by) qs.set('sort_by', params.sort_by)
  if (params.sort_dir !== undefined) qs.set('sort_dir', String(params.sort_dir))
  if (params.limit !== undefined) qs.set('limit', String(params.limit))
  if (params.offset !== undefined) qs.set('offset', String(params.offset))
  const url = `${BASE}/runs?${qs}`

  return useQuery({
    queryKey: ['strangle-backtests', 'runs', params],
    queryFn: () => apiFetch<{ total: number; runs: BacktestRun[]; limit: number; offset: number }>(url),
    staleTime: 30_000,
  })
}

export function useRun(runId: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'run', runId],
    queryFn: () => apiFetch<BacktestRun>(`${BASE}/runs/${runId}`),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useRunEquity(runId: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'equity', runId],
    queryFn: () => apiFetch<{ run_id: string; equity: EquityPoint[] }>(`${BASE}/runs/${runId}/equity`),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useRunDays(runId: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'days', runId],
    queryFn: () => apiFetch<{ run_id: string; days: DayRow[] }>(`${BASE}/runs/${runId}/days`),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useRunFolds(runId: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'folds', runId],
    queryFn: () =>
      apiFetch<{ run_id: string; verdict: string | null; stitched_oos: Record<string, unknown> | null; folds: FoldDoc[] }>(
        `${BASE}/runs/${runId}/folds`,
      ),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useDayTrades(runId: string | null, date: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'trades', runId, date],
    queryFn: () => apiFetch<{ run_id: string; date: string; fills: Fill[] }>(`${BASE}/runs/${runId}/days/${date}/trades`),
    enabled: !!runId && !!date,
    staleTime: 60_000,
  })
}

export function useDayStatus(runId: string | null, date: string | null) {
  return useQuery({
    queryKey: ['strangle-backtests', 'status', runId, date],
    queryFn: () => apiFetch<{ run_id: string; date: string; status_log: string[] }>(`${BASE}/runs/${runId}/days/${date}/status`),
    enabled: !!runId && !!date,
    staleTime: 60_000,
  })
}

export function useCompareRuns(runIds: string[]) {
  return useQuery({
    queryKey: ['strangle-backtests', 'compare', runIds],
    queryFn: () =>
      apiFetch<{ runs: Array<{ run_id: string; metrics: RunMetrics; equity: EquityPoint[]; verdict: string | null }> }>(
        `${BASE}/compare`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_ids: runIds }),
        },
      ),
    enabled: runIds.length > 0,
    staleTime: 60_000,
  })
}

// ── Launch mutations ──────────────────────────────────────────────────────────

export function useLaunchSingle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { config: Record<string, unknown>; date_from: string; date_to: string; mongo?: boolean }) =>
      apiFetch<{ job_id: string; type: string; status: string }>(`${BASE}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strangle-backtests', 'runs'] }),
  })
}

export function useLaunchWalkforward() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      config: Record<string, unknown>; date_from: string; date_to: string
      is_months?: number; oos_months?: number; objective?: string; mongo?: boolean
    }) =>
      apiFetch<{ job_id: string; type: string; status: string }>(`${BASE}/walkforwards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strangle-backtests', 'runs'] }),
  })
}

// ── Promote mutation ──────────────────────────────────────────────────────────

export function usePromoteRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) =>
      apiFetch<{ strategy_id: string; yaml_path: string; promoted_at: string }>(`${BASE}/runs/${runId}/promote`, {
        method: 'POST',
      }),
    onSuccess: (_data, runId) => {
      qc.invalidateQueries({ queryKey: ['strangle-backtests', 'run', runId] })
      qc.invalidateQueries({ queryKey: ['strangle-backtests', 'runs'] })
    },
  })
}
