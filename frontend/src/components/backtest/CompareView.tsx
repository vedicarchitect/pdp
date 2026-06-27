import { ArrowLeft, X } from 'lucide-react'
import {
  ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from 'recharts'
import { chartTheme } from '@/lib/chartTheme'
import type { RunMetrics, EquityPoint } from '@/hooks/useStrangleBacktests'
import { useCompareRuns } from '@/hooks/useStrangleBacktests'
import { Card, CardContent } from '@/components/ui/Card'

interface CompareRunResult { run_id: string; kind?: string; metrics: RunMetrics; equity: EquityPoint[]; verdict: string | null }

const _fmtPF = (v: number | null | undefined) =>
  v == null ? '—' : v === Infinity ? '∞' : v.toFixed(2)

const _fmtK = (v: number | null | undefined) =>
  v == null ? '—' : `₹${(v / 1000).toFixed(0)}K`

interface Props {
  runIds: string[]
  onRemove: (id: string) => void
  onBack: () => void
}

export function CompareView({ runIds, onRemove, onBack }: Props) {
  const { data, isLoading } = useCompareRuns(runIds)

  const series: CompareRunResult[] = data?.runs ?? []

  // Build merged chart data — align by date index across all runs
  const dateSet = new Set<string>()
  for (const r of series) {
    for (const pt of r.equity) dateSet.add(pt.date)
  }
  const allDates = Array.from(dateSet).sort()

  const chartData = allDates.map((date) => {
    const row: Record<string, unknown> = { date: date.slice(5) }
    for (const r of series) {
      const pt = r.equity.find((e) => e.date === date)
      row[r.run_id] = pt?.cum_equity ?? null
    }
    return row
  })

  return (
    <div className="flex flex-col gap-4" data-testid="compare-view">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded hover:bg-surface-border text-text-muted">
          <ArrowLeft size={16} />
        </button>
        <p className="text-sm font-medium text-text-main">Compare {runIds.length} Runs</p>
      </div>

      {/* Run chips */}
      <div className="flex flex-wrap gap-2">
        {runIds.map((id) => (
          <span key={id} className="flex items-center gap-1 px-2 py-0.5 bg-surface-card border border-surface-border rounded text-xs font-mono">
            {id}
            <button onClick={() => onRemove(id)} className="text-text-muted hover:text-bearish"><X size={10} /></button>
          </span>
        ))}
      </div>

      {isLoading && <p className="text-sm text-text-muted py-4">Loading comparison…</p>}

      {/* Overlay equity chart */}
      {chartData.length > 0 && !isLoading && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-muted mb-2">Equity Curves (overlaid)</p>
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid.color} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                  tickFormatter={(v) => `₹${(v / 100000).toFixed(0)}L`} width={52} />
                <Tooltip
                  contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 6 }}
                  formatter={(val: unknown, name: unknown) => [`₹${Number(val ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, String(name ?? '').slice(-20)]}
                />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <ReferenceLine y={0} stroke="var(--color-text-muted)" strokeDasharray="4 2" />
                {series.map((r, i) => (
                  <Line
                    key={r.run_id}
                    type="monotone"
                    dataKey={r.run_id}
                    stroke={chartTheme.colors.series[i % chartTheme.colors.series.length]}
                    dot={false}
                    strokeWidth={1.5}
                    connectNulls
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Headline metrics comparison table */}
      {series.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-4 py-2 border-b border-surface-border text-xs text-text-muted font-medium">Metrics</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-card/50">
                <tr className="text-xs text-text-muted">
                  <th className="px-3 py-1.5 text-left font-medium">Run</th>
                  <th className="px-3 py-1.5 text-left font-medium">Kind</th>
                  <th className="px-3 py-1.5 text-left font-medium">Verdict</th>
                  <th className="px-3 py-1.5 text-left font-medium">Net</th>
                  <th className="px-3 py-1.5 text-left font-medium">PF</th>
                  <th className="px-3 py-1.5 text-left font-medium">Sharpe</th>
                  <th className="px-3 py-1.5 text-left font-medium">MaxDD</th>
                  <th className="px-3 py-1.5 text-left font-medium">Win%</th>
                  <th className="px-3 py-1.5 text-left font-medium">Trades</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border/30">
                {series.map((r, i) => {
                  const m = r.metrics
                  return (
                    <tr key={r.run_id} className="hover:bg-surface-card/30">
                      <td className="px-3 py-1.5 font-mono text-xs" style={{ color: chartTheme.colors.series[i % chartTheme.colors.series.length] }}>
                        {r.run_id}
                      </td>
                      <td className="px-3 py-1.5 text-xs text-text-muted">{r.kind ?? '—'}</td>
                      <td className="px-3 py-1.5 text-xs">{r.verdict ?? '—'}</td>
                      <td className={`px-3 py-1.5 tabular-nums text-xs font-medium ${(m.net ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                        {_fmtK(m.net)}
                      </td>
                      <td className="px-3 py-1.5 tabular-nums text-xs">{_fmtPF(m.profit_factor)}</td>
                      <td className="px-3 py-1.5 tabular-nums text-xs">{m.sharpe?.toFixed(2) ?? '—'}</td>
                      <td className="px-3 py-1.5 tabular-nums text-xs text-bearish">{_fmtK(m.max_dd)}</td>
                      <td className="px-3 py-1.5 tabular-nums text-xs">{m.win_rate?.toFixed(0) ?? '—'}%</td>
                      <td className="px-3 py-1.5 tabular-nums text-xs">{m.trades}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
