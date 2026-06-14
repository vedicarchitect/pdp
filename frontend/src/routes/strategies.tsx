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
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Strategies</h1>

      <section className="space-y-2">
        {(strategies ?? []).map((s) => {
          const running = s.status === 'RUNNING'
          return (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
            >
              <div>
                <div className="font-medium">{s.id}</div>
                <div className="text-sm text-neutral-500">
                  {s.status}
                  {s.dropped_ticks ? ` · ${s.dropped_ticks} dropped` : ''}
                </div>
              </div>
              <button
                className={`rounded-md px-3 py-1.5 text-sm font-medium text-white transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-surface ${
                  running ? 'bg-bearish hover:bg-bearish/90 focus-visible:ring-bearish' : 'bg-bullish hover:bg-bullish/90 focus-visible:ring-bullish'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
                disabled={toggle.isPending}
                aria-busy={toggle.isPending && toggle.variables?.id === s.id}
                aria-label={running ? `Stop strategy ${s.id}` : `Start strategy ${s.id}`}
                onClick={() => toggle.mutate({ id: s.id, action: running ? 'stop' : 'start' })}
              >
                {toggle.isPending && toggle.variables?.id === s.id
                  ? running ? 'Stopping...' : 'Starting...'
                  : running ? 'Stop' : 'Start'}
              </button>
            </div>
          )
        })}
        {strategies && strategies.length === 0 && (
          <p className="text-sm text-neutral-500">No strategies registered.</p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          Paper journal {journal?.date ? <span className="text-neutral-500">· {journal.date}</span> : null}
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

        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-neutral-500 dark:bg-neutral-900">
              <tr>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Security</th>
                <th className="px-3 py-2">Side</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Charges</th>
              </tr>
            </thead>
            <tbody>
              {(journal?.trades ?? []).map((t, i) => (
                <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800">
                  <td className="px-3 py-1.5 text-neutral-500">{t.ts.slice(11, 19)}</td>
                  <td className="px-3 py-1.5 font-mono">{t.security_id}</td>
                  <td className={`px-3 py-1.5 ${t.side === 'SELL' ? 'text-green-600' : 'text-red-600'}`}>
                    {t.side}
                  </td>
                  <td className="px-3 py-1.5 text-right">{t.qty}</td>
                  <td className="px-3 py-1.5 text-right">{t.fill_price}</td>
                  <td className="px-3 py-1.5 text-right text-neutral-500">{t.charges}</td>
                </tr>
              ))}
              {journal && journal.trades.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-3 text-center text-neutral-500">
                    No fills yet today.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <div className="text-xs text-neutral-500">{label}</div>
      <div
        className={`text-lg font-semibold ${
          positive === undefined ? '' : positive ? 'text-green-600' : 'text-red-600'
        }`}
      >
        {value}
      </div>
    </div>
  )
}
