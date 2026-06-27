import { ArrowLeft } from 'lucide-react'
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import { chartTheme } from '@/lib/chartTheme'
import type { BacktestRun } from '@/hooks/useStrangleBacktests'
import { useRunFolds } from '@/hooks/useStrangleBacktests'
import { Badge } from '@/components/ui/Badge'
import { Card, CardContent } from '@/components/ui/Card'

const _fmtPF = (v: number | null | undefined) =>
  v == null ? '—' : v === Infinity ? '∞' : v.toFixed(2)

const _fmtK = (v: number | null | undefined) =>
  v == null ? '—' : `₹${(v / 1000).toFixed(0)}K`

interface Props { run: BacktestRun; onBack: () => void }

export function WalkForwardView({ run, onBack }: Props) {
  const { data, isLoading } = useRunFolds(run.run_id)

  const folds = data?.folds ?? []
  const verdict = data?.verdict ?? null
  const stitched = data?.stitched_oos as Record<string, number | null> | null | undefined

  // Build stitched-OOS equity series from cumulative fold OOS nets
  const stitchedEquity: Array<{ fold: string; cum: number }> = []
  let cum = 0
  for (const f of folds) {
    cum += f.oos_metrics.net ?? 0
    stitchedEquity.push({ fold: `F${f.fold_index}`, cum })
  }

  if (isLoading) return (
    <div className="py-8 text-center text-text-muted text-sm">Loading folds…</div>
  )

  return (
    <div className="flex flex-col gap-4" data-testid="walkforward-view">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded hover:bg-surface-border text-text-muted">
          <ArrowLeft size={16} />
        </button>
        <div>
          <p className="text-sm font-medium text-text-main">Walk-Forward — {run.run_id}</p>
          <p className="text-xs text-text-muted">{folds.length} folds</p>
        </div>
        {verdict && (
          <Badge variant={verdict === 'PASS' ? 'success' : 'warning'} className="ml-auto">
            {verdict}
          </Badge>
        )}
      </div>

      {/* Stitched OOS summary cards */}
      {stitched && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: 'OOS Net', value: _fmtK(stitched.net) },
            { label: 'OOS PF', value: _fmtPF(stitched.profit_factor) },
            { label: 'OOS Sharpe', value: stitched.sharpe != null ? Number(stitched.sharpe).toFixed(2) : '—' },
            { label: 'Positive Folds', value: `${stitched.positive_folds ?? 0}/${stitched.folds ?? 0}` },
          ].map((item) => (
            <div key={item.label} className="p-3 bg-surface-card rounded border border-surface-border/50">
              <p className="text-xs text-text-muted">{item.label}</p>
              <p className="text-base font-bold text-text-main tabular-nums">{item.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Stitched OOS equity */}
      {stitchedEquity.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-muted mb-2">Stitched OOS Equity (fold-by-fold)</p>
            <ResponsiveContainer width="100%" height={160}>
              <AreaChart data={stitchedEquity} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid.color} />
                <XAxis dataKey="fold" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                  tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}K`} width={52} />
                <Tooltip
                  contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 6 }}
                  formatter={(val: unknown) => [`₹${Number(val ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, 'Cum OOS']}
                />
                <ReferenceLine y={0} stroke="var(--color-text-muted)" strokeDasharray="4 2" />
                <Area type="monotone" dataKey="cum" stroke={chartTheme.colors.profit}
                  fill={`${chartTheme.colors.profit}22`} strokeWidth={2} dot />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Per-fold table */}
      <Card className="overflow-hidden">
        <div className="px-4 py-2 border-b border-surface-border text-xs text-text-muted font-medium">
          Per-Fold IS vs OOS
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-card/50">
              <tr className="text-xs text-text-muted">
                {['Fold', 'IS Window', 'OOS Window', 'Pick', 'IS Net', 'IS PF', 'IS Sharpe',
                  'OOS Net', 'OOS PF', 'OOS Win%', 'OOS Sharpe', 'OOS MaxDD'].map((h) => (
                  <th key={h} className="px-3 py-1.5 text-left font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border/30">
              {folds.map((f) => (
                <tr key={f.fold_index} className="hover:bg-surface-card/30">
                  <td className="px-3 py-1.5 tabular-nums font-medium">{f.fold_index}</td>
                  <td className="px-3 py-1.5 text-xs text-text-muted whitespace-nowrap">
                    {f.is_window.start.slice(0, 10)}→{f.oos_window.start.slice(0, 10)}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-text-muted whitespace-nowrap">
                    {f.oos_window.start.slice(0, 10)}→{f.oos_window.end.slice(0, 10)}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-xs">{f.pick_label}</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{_fmtK(f.is_metrics.net)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{_fmtPF(f.is_metrics.profit_factor)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{f.is_metrics.sharpe?.toFixed(2) ?? '—'}</td>
                  <td className={`px-3 py-1.5 tabular-nums text-xs font-medium ${(f.oos_metrics.net ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                    {_fmtK(f.oos_metrics.net)}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{_fmtPF(f.oos_metrics.profit_factor)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{f.oos_metrics.win_rate?.toFixed(0) ?? '—'}%</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs">{f.oos_metrics.sharpe?.toFixed(2) ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums text-xs text-bearish">{_fmtK(f.oos_metrics.max_dd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
