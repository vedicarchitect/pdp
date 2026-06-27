import { useState } from 'react'
import { ArrowLeft, ChevronDown, ChevronRight } from 'lucide-react'
import {
  ResponsiveContainer, ComposedChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import { chartTheme } from '@/lib/chartTheme'
import type { BacktestRun } from '@/hooks/useStrangleBacktests'
import { useRunEquity, useRunDays, usePromoteRun } from '@/hooks/useStrangleBacktests'
import { Badge } from '@/components/ui/Badge'
import { Card, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'

const _fmt = (v: number | null | undefined, digits = 0) =>
  v == null ? '—' : `₹${v.toLocaleString('en-IN', { maximumFractionDigits: digits })}`

const _fmtPF = (v: number | null | undefined) =>
  v == null ? '—' : v === Infinity ? '∞' : v.toFixed(2)

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col gap-0.5 p-3 bg-surface-card rounded border border-surface-border/50">
      <span className="text-xs text-text-muted">{label}</span>
      <span className="text-lg font-bold text-text-main tabular-nums">{value}</span>
      {sub && <span className="text-xs text-text-muted">{sub}</span>}
    </div>
  )
}

interface Props {
  run: BacktestRun
  onBack: () => void
  onSelectDay: (date: string) => void
}

export function RunDetail({ run, onBack, onSelectDay }: Props) {
  const { data: equityData } = useRunEquity(run.run_id)
  const { data: daysData } = useRunDays(run.run_id)
  const [showConfig, setShowConfig] = useState(false)
  const promote = usePromoteRun()
  const { toast } = useToast()

  const equity = equityData?.equity ?? []
  const days = daysData?.days ?? []
  const m = run.metrics

  function handlePromote() {
    if (!window.confirm(`Promote ${run.run_id} to a paper strategy?\nThis generates strategies/<id>.yaml.`)) return
    promote.mutate(run.run_id, {
      onSuccess: (r) => toast({ variant: 'success', title: 'Promoted!', description: `Strategy: ${r.strategy_id}` }),
      onError: (e: Error) => toast({ variant: 'error', title: 'Promotion failed', description: e.message }),
    })
  }

  const canPromote = run.kind === 'walkforward' && run.verdict === 'PASS' && run.promotion_state === 'none'

  return (
    <div className="flex flex-col gap-4" data-testid="run-detail">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded hover:bg-surface-border text-text-muted">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm text-text-main truncate">{run.run_id}</span>
            <Badge variant={run.kind === 'walkforward' ? 'info' : 'outline'} size="sm">{run.kind}</Badge>
            {run.verdict && (
              <Badge variant={run.verdict === 'PASS' ? 'success' : 'warning'} size="sm">{run.verdict}</Badge>
            )}
            {run.promotion_state === 'promoted' && <Badge variant="success" size="sm">promoted</Badge>}
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            {run.window?.from?.slice(0, 10)} → {run.window?.to?.slice(0, 10)}
            {run.window?.traded_days != null && ` · ${run.window.traded_days} traded days`}
          </p>
        </div>
        {canPromote && (
          <Button onClick={handlePromote} disabled={promote.isPending} size="sm" className="shrink-0">
            {promote.isPending ? 'Promoting…' : 'Promote to Paper'}
          </Button>
        )}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <MetricCard label="Net P&L" value={_fmt(m.net)} />
        <MetricCard label="Profit Factor" value={_fmtPF(m.profit_factor)} />
        <MetricCard label="Win Rate" value={m.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'} />
        <MetricCard label="Max Drawdown" value={_fmt(m.max_dd)} />
        <MetricCard label="Sharpe" value={m.sharpe != null ? m.sharpe.toFixed(2) : '—'} />
        <MetricCard label="Calmar" value={m.calmar != null ? m.calmar.toFixed(2) : '—'} />
        <MetricCard label="Trades" value={String(m.trades)} sub={`${m.halted} halted`} />
      </div>

      {/* Equity + Drawdown chart */}
      {equity.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-muted mb-2">Equity Curve &amp; Drawdown</p>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={equity} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid.color} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                  tickFormatter={(v) => v.slice(5)} interval="preserveStartEnd" />
                <YAxis yAxisId="eq" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                  tickFormatter={(v) => `₹${(v / 100000).toFixed(0)}L`} width={52} />
                <YAxis yAxisId="dd" orientation="right" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                  tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}K`} width={52} />
                <Tooltip
                  contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 6 }}
                  labelStyle={{ color: chartTheme.tooltip.text, fontSize: 11 }}
                  formatter={(val: unknown, name: unknown) => [`₹${Number(val ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`, String(name ?? '')]}
                />
                <ReferenceLine yAxisId="eq" y={0} stroke="var(--color-text-muted)" strokeDasharray="4 2" />
                <Area yAxisId="eq" type="monotone" dataKey="cum_equity" name="Equity"
                  stroke={chartTheme.colors.profit} fill={`${chartTheme.colors.profit}22`} strokeWidth={1.5} dot={false} />
                <Area yAxisId="dd" type="monotone" dataKey="drawdown" name="Drawdown"
                  stroke={chartTheme.colors.loss} fill={`${chartTheme.colors.loss}22`} strokeWidth={1} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Per-day P&L table */}
      {days.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-4 py-2 border-b border-surface-border text-xs text-text-muted font-medium">
            Per-day P&amp;L ({days.length} days)
          </div>
          <div className="overflow-x-auto max-h-72">
            <table className="w-full text-sm">
              <thead className="bg-surface-card/50 sticky top-0">
                <tr className="text-xs text-text-muted">
                  {['Date', 'Expiry', 'NIFTY Chg', 'Trades', 'Gross', 'Comm', 'Net', 'Cum Equity', 'DD', 'Status'].map((h) => (
                    <th key={h} className="px-3 py-1.5 text-left whitespace-nowrap font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border/30">
                {days.map((d) => (
                  <tr key={d.date} className="hover:bg-surface-card/30 cursor-pointer" onClick={() => onSelectDay(d.date)}>
                    <td className="px-3 py-1.5 font-mono text-xs text-primary">{d.date}</td>
                    <td className="px-3 py-1.5 text-xs text-text-muted">{d.expiry?.slice(5)}</td>
                    <td className={`px-3 py-1.5 tabular-nums text-xs ${(d.nifty_close ?? 0) >= (d.nifty_open ?? 0) ? 'text-bullish' : 'text-bearish'}`}>
                      {d.nifty_open != null && d.nifty_close != null ? `${(d.nifty_close - d.nifty_open) >= 0 ? '+' : ''}${(d.nifty_close - d.nifty_open).toFixed(0)}` : '—'}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-center">{d.trades}</td>
                    <td className={`px-3 py-1.5 tabular-nums text-xs ${(d.gross_pnl ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                      {d.gross_pnl != null ? `₹${d.gross_pnl.toFixed(0)}` : '—'}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-xs text-text-muted">{d.commission != null ? `₹${d.commission.toFixed(0)}` : '—'}</td>
                    <td className={`px-3 py-1.5 tabular-nums text-xs font-medium ${(d.net ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                      {d.net != null ? `₹${d.net.toFixed(0)}` : '—'}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-xs">{d.cum_equity != null ? `₹${d.cum_equity.toFixed(0)}` : '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums text-xs text-bearish">{d.drawdown != null && d.drawdown > 0 ? `₹${d.drawdown.toFixed(0)}` : ''}</td>
                    <td className="px-3 py-1.5 text-xs text-text-muted">{d.halted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Config viewer */}
      <Card>
        <button
          onClick={() => setShowConfig((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-2 text-xs text-text-muted hover:text-text-main"
        >
          <span>Run Config</span>
          {showConfig ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {showConfig && (
          <pre className="px-4 pb-3 text-xs text-text-muted overflow-x-auto max-h-60 font-mono leading-relaxed">
            {JSON.stringify(run.config, null, 2)}
          </pre>
        )}
      </Card>
    </div>
  )
}
