import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export const Route = createFileRoute('/strategies')({
  component: StrategiesPage,
})

type StrategyInfo = {
  id: string
  status: 'RUNNING' | 'STOPPED' | 'CRASHED'
  dropped_ticks?: number
  watchlist?: { security_id: string; exchange_segment: string; timeframes: string[] }[]
}

type JournalStats = {
  total_trades: number
  realized_pnl: number
  net_premium: number
  total_charges: number
  round_trips: number
  wins: number
  losses: number
  win_rate: number
  gross_premium_sold: number
  gross_premium_bought: number
}

type JournalDay = {
  date: string
  trades: {
    ts: string
    security_id: string
    side: string
    qty: number
    fill_price: string
    charges: string
    strategy_id?: string | null
  }[]
  stats: JournalStats
}

async function fetchStrategies(): Promise<StrategyInfo[]> {
  const res = await fetch('/api/v1/strategies')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchJournal(): Promise<JournalDay> {
  const res = await fetch('/api/v1/journal')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function inr(n: number): string {
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'

function statusBadgeVariant(status: StrategyInfo['status']): 'success' | 'warning' | 'danger' | 'default' {
  switch (status) {
    case 'RUNNING': return 'success'
    case 'STOPPED': return 'default'
    case 'CRASHED': return 'danger'
  }
}

function StrategiesPage() {
  const qc = useQueryClient()
  const { data: strategies } = useQuery({
    queryKey: ['strategies'],
    queryFn: fetchStrategies,
    refetchInterval: 5000,
  })
  const { data: journal } = useQuery({
    queryKey: ['journal'],
    queryFn: fetchJournal,
    refetchInterval: 5000,
  })

  const toggle = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: 'start' | 'stop' }) => {
      const res = await fetch(`/api/v1/strategies/${id}/${action}`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strategies'] }),
  })

  const stats = journal?.stats
  const pnl = stats?.realized_pnl ?? 0

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-text-main tracking-tight">Strategies</h1>

      <section className="flex flex-col gap-2">
        {(strategies ?? []).map((s) => {
          const running = s.status === 'RUNNING'
          return (
            <Card
              key={s.id}
              className="flex items-center justify-between p-4 transition-colors hover:bg-surface-hover"
            >
              <div className="flex items-center gap-3">
                <Badge variant={statusBadgeVariant(s.status)}>
                  {s.status}
                </Badge>
                <div>
                  <div className="font-semibold text-text-main">{s.id}</div>
                  {s.dropped_ticks ? (
                    <div className="text-xs text-warning">
                      {s.dropped_ticks} dropped ticks
                    </div>
                  ) : null}
                </div>
              </div>
              <Button
                variant={running ? 'danger' : 'primary'}
                disabled={toggle.isPending}
                onClick={() => toggle.mutate({ id: s.id, action: running ? 'stop' : 'start' })}
              >
                {running ? 'Stop' : 'Start'}
              </Button>
            </Card>
          )
        })}
        {strategies && strategies.length === 0 && (
          <p className="text-sm text-text-muted">No strategies registered.</p>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-text-main">
          Paper Journal{' '}
          {journal?.date ? <span className="text-text-muted font-normal">· {journal.date}</span> : null}
        </h2>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Realized P&L" value={inr(pnl)} positive={pnl >= 0} />
          <Stat label="Net premium" value={inr(stats?.net_premium ?? 0)} />
          <Stat label="Round-trips" value={String(stats?.round_trips ?? 0)} />
          <Stat
            label="Win rate"
            value={`${Math.round((stats?.win_rate ?? 0) * 100)}% (${stats?.wins ?? 0}/${
              (stats?.wins ?? 0) + (stats?.losses ?? 0)
            })`}
          />
          <Stat label="Premium sold" value={inr(stats?.gross_premium_sold ?? 0)} />
          <Stat label="Premium bought" value={inr(stats?.gross_premium_bought ?? 0)} />
          <Stat label="Charges" value={inr(stats?.total_charges ?? 0)} />
          <Stat label="Fills" value={String(stats?.total_trades ?? 0)} />
        </div>

        <Card className="overflow-x-auto rounded-xl">
          <table className="w-full text-sm text-left">
            <thead className="bg-surface text-xs text-text-muted uppercase tracking-wider font-semibold border-b border-surface-border">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Security</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-right">Charges</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {(journal?.trades ?? []).map((t, i) => (
                <tr key={i} className="hover:bg-surface-hover transition-colors">
                  <td className="px-4 py-2 text-text-muted">{t.ts.slice(11, 19)}</td>
                  <td className="px-4 py-2 font-mono text-text-main">{t.security_id}</td>
                  <td className={`px-4 py-2 font-semibold ${t.side === 'SELL' ? 'text-bullish' : 'text-bearish'}`}>
                    {t.side}
                  </td>
                  <td className="px-4 py-2 text-right text-text-main">{t.qty}</td>
                  <td className="px-4 py-2 text-right font-mono text-text-main">{t.fill_price}</td>
                  <td className="px-4 py-2 text-right text-text-muted">{t.charges}</td>
                </tr>
              ))}
              {journal && journal.trades.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-text-muted">
                    No fills yet today.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  )
}

function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <Card className="p-3 transition-transform duration-200 hover:-translate-y-0.5">
      <div className="text-xs text-text-muted mb-1 uppercase tracking-wider">{label}</div>
      <div
        className={`text-lg font-semibold font-mono ${
          positive === undefined ? 'text-text-main' : positive ? 'text-bullish' : 'text-bearish'
        }`}
      >
        {value}
      </div>
    </Card>
  )
}
