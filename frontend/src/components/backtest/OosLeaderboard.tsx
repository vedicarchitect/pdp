import { useState } from 'react'
import { Trophy } from 'lucide-react'
import { useRunsList } from '@/hooks/useStrangleBacktests'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import type { BacktestRun } from '@/hooks/useStrangleBacktests'

const METRICS: Array<{ key: string; label: string }> = [
  { key: 'sharpe', label: 'Sharpe' },
  { key: 'pf', label: 'Profit Factor' },
  { key: 'net', label: 'Net P&L' },
  { key: 'max_dd', label: 'MaxDD (ascending)' },
]

function medal(rank: number) {
  if (rank === 1) return '🥇'
  if (rank === 2) return '🥈'
  if (rank === 3) return '🥉'
  return String(rank)
}

interface Props {
  onSelect: (run: BacktestRun) => void
}

export function OosLeaderboard({ onSelect }: Props) {
  const [metric, setMetric] = useState('sharpe')

  const { data, isLoading } = useRunsList({
    kind: 'walkforward',
    sort_by: metric,
    sort_dir: metric === 'max_dd' ? 1 : -1,
    limit: 20,
  })

  const runs = data?.runs ?? []

  return (
    <div className="flex flex-col gap-3" data-testid="oos-leaderboard">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Trophy size={14} className="text-warning" />
          <span className="text-sm font-medium text-text-main">OOS Leaderboard</span>
          <span className="text-xs text-text-muted">(walk-forward runs)</span>
        </div>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          className="bg-surface-card border border-surface-border rounded px-2 py-1 text-xs text-text-main focus:outline-none"
        >
          {METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="py-8 text-center text-text-muted text-sm">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="py-8 text-center text-text-muted text-sm">No walk-forward runs found</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-card/50">
                <tr className="text-xs text-text-muted">
                  <th className="px-3 py-2 text-left font-medium">#</th>
                  <th className="px-3 py-2 text-left font-medium">Run</th>
                  <th className="px-3 py-2 text-left font-medium">Verdict</th>
                  <th className="px-3 py-2 text-left font-medium">Net</th>
                  <th className="px-3 py-2 text-left font-medium">PF</th>
                  <th className="px-3 py-2 text-left font-medium">Sharpe</th>
                  <th className="px-3 py-2 text-left font-medium">MaxDD</th>
                  <th className="px-3 py-2 text-left font-medium">Win%</th>
                  <th className="px-3 py-2 text-left font-medium">Window</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border/30">
                {runs.map((run, i) => {
                  const m = run.metrics
                  return (
                    <tr
                      key={run.run_id}
                      className="hover:bg-surface-card/30 cursor-pointer"
                      onClick={() => onSelect(run)}
                    >
                      <td className="px-3 py-2 text-sm font-mono">{medal(i + 1)}</td>
                      <td className="px-3 py-2">
                        <span className="font-mono text-xs text-primary hover:underline max-w-[160px] truncate block" title={run.run_id}>
                          {run.run_id}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {run.verdict ? (
                          <Badge variant={run.verdict === 'PASS' ? 'success' : 'warning'} size="sm">{run.verdict}</Badge>
                        ) : '—'}
                      </td>
                      <td className={`px-3 py-2 tabular-nums text-xs font-medium ${(m.net ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                        ₹{m.net != null ? (m.net / 100000).toFixed(1) : '—'}L
                      </td>
                      <td className="px-3 py-2 tabular-nums text-xs">{m.profit_factor != null ? m.profit_factor.toFixed(2) : '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-xs">{m.sharpe != null ? m.sharpe.toFixed(2) : '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-xs text-bearish">{m.max_dd != null ? `₹${(m.max_dd / 1000).toFixed(0)}K` : '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-xs">{m.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'}</td>
                      <td className="px-3 py-2 text-xs text-text-muted whitespace-nowrap">
                        {run.window?.from?.slice(0, 10)} → {run.window?.to?.slice(0, 10)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
