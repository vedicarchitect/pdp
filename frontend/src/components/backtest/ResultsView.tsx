import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs'
import { EquityCurve } from './EquityCurve'
import { DayWiseTable } from './DayWiseTable'
import { TradeLog } from './TradeLog'
import { cn } from '@/lib/utils'

interface BacktestResults {
  config_name: string
  date_range: { from: string; to: string }
  summary: {
    total_pnl: number
    total_trades: number
    win_rate: number
    max_drawdown: number
    max_drawdown_pct: number
    sharpe_ratio: number | null
    commissions_total: number
  }
  equity_curve: Array<{ date: string; cumulative_pnl: number }>
  daily_pnl: Array<{
    date: string
    pnl: number
    trades: number
    re_entries: number
    weekday: string
  }>
  weekday_stats: Record<string, { avg_pnl: number; win_rate: number; count: number }>
  trade_log: Array<{
    date: string
    entry_time: string
    exit_time: string
    legs: Array<{
      type: string
      side: string
      strike: number
      lots: number
      entry_price: number
      exit_price: number
      pnl_points: number
    }>
    pnl: number
    exit_reason: string
    re_entry_count: number
  }>
}

function StatCard({ label, value, sub, positive }: { label: string; value: string; sub?: string; positive?: boolean }) {
  return (
    <div className="flex flex-col gap-1 p-3 rounded-lg border border-surface-border bg-surface-raised/40">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={cn('text-lg font-bold font-mono', positive === true ? 'text-bullish' : positive === false ? 'text-bearish' : 'text-text-main')}>
        {value}
      </span>
      {sub && <span className="text-xs text-text-muted">{sub}</span>}
    </div>
  )
}

function WeekdayStats({ stats }: { stats: Record<string, { avg_pnl: number; win_rate: number; count: number }> }) {
  const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
  return (
    <div className="grid grid-cols-5 gap-2">
      {DAYS.map((d) => {
        const s = stats[d]
        if (!s) return <div key={d} className="text-center text-xs text-text-muted capitalize">{d.slice(0, 3)}</div>
        return (
          <div key={d} className="flex flex-col items-center gap-1 p-2 rounded border border-surface-border bg-surface-raised/30">
            <span className="text-xs text-text-muted capitalize">{d.slice(0, 3)}</span>
            <span className={cn('text-sm font-mono font-medium', s.avg_pnl >= 0 ? 'text-bullish' : 'text-bearish')}>
              {s.avg_pnl >= 0 ? '+' : ''}₹{Math.abs(s.avg_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
            <span className="text-xs text-text-muted">{(s.win_rate * 100).toFixed(0)}% • {s.count}d</span>
          </div>
        )
      })}
    </div>
  )
}

interface Props {
  results: BacktestResults
}

export function ResultsView({ results }: Props) {
  const { summary } = results

  return (
    <div className="flex flex-col gap-4">
      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard
          label="Total P&L"
          value={`${summary.total_pnl >= 0 ? '+' : ''}₹${Math.abs(summary.total_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          positive={summary.total_pnl >= 0}
        />
        <StatCard
          label="Win Rate"
          value={`${(summary.win_rate * 100).toFixed(1)}%`}
          positive={summary.win_rate >= 0.5}
        />
        <StatCard
          label="Max Drawdown"
          value={`₹${summary.max_drawdown.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          sub={`${summary.max_drawdown_pct.toFixed(1)}%`}
          positive={false}
        />
        <StatCard
          label="Sharpe"
          value={summary.sharpe_ratio !== null ? summary.sharpe_ratio.toFixed(2) : '—'}
          positive={summary.sharpe_ratio !== null && summary.sharpe_ratio > 0}
        />
        <StatCard label="Trades" value={String(summary.total_trades)} />
        <StatCard
          label="Commissions"
          value={`₹${summary.commissions_total.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
        />
      </div>

      {/* Equity curve */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent>
          <EquityCurve data={results.equity_curve} />
        </CardContent>
      </Card>

      {/* Tabs: Day-wise, Weekday stats, Trade log */}
      <Tabs defaultValue="daywise">
        <TabsList>
          <TabsTrigger value="daywise">Day-wise P&L</TabsTrigger>
          <TabsTrigger value="weekday">Weekday Stats</TabsTrigger>
          <TabsTrigger value="trades">Trade Log ({results.trade_log.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="daywise">
          <Card>
            <CardContent className="pt-4">
              <DayWiseTable data={results.daily_pnl} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="weekday">
          <Card>
            <CardContent className="pt-4">
              <WeekdayStats stats={results.weekday_stats} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trades">
          <Card>
            <CardContent className="pt-4">
              <TradeLog data={results.trade_log} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
