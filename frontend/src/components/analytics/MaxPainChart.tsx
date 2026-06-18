import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import { Lock } from 'lucide-react'
import { chartTheme } from '@/lib/chartTheme'

interface Props {
  underlying: string
  expiry?: string
}

interface StrikeData {
  strike: number
  ce: { oi: number; ltp: number }
  pe: { oi: number; ltp: number }
}

interface ChainResponse {
  mode?: string
  strikes: StrikeData[]
  max_pain: number | null
  spot_price: number | null
}

function computePain(strikes: StrikeData[], candidate: number): number {
  return strikes.reduce((acc, s) => {
    const cePain = Math.max(0, s.strike - candidate) * (s.ce?.oi ?? 0)
    const pePain = Math.max(0, candidate - s.strike) * (s.pe?.oi ?? 0)
    return acc + cePain + pePain
  }, 0)
}

function PaperModePlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
      <Lock size={32} />
      <p className="text-sm">Live data requires LIVE=1 and Dhan credentials</p>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="h-64 flex items-center justify-center">
      <div className="animate-pulse text-text-muted text-sm">Loading…</div>
    </div>
  )
}

export function MaxPainChart({ underlying, expiry }: Props) {
  const params = new URLSearchParams()
  if (expiry) params.set('expiry', expiry)
  const url = `/api/v1/options/${underlying}/chain${params.size ? '?' + params : ''}`

  const { data, isLoading } = useQuery<ChainResponse>({
    queryKey: ['options-chain', underlying, expiry],
    queryFn: () => fetch(url).then((r) => r.json()),
    refetchInterval: 30_000,
  })

  if (isLoading) return <LoadingSkeleton />
  if (!data || data.mode === 'paper') return <PaperModePlaceholder />

  const chartData = data.strikes.map((s) => ({
    strike: s.strike,
    pain: computePain(data.strikes, s.strike),
  }))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-4 text-xs text-text-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-amber-400" /> Max Pain: {data.max_pain ?? '—'}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-blue-400" /> Spot: {data.spot_price ?? '—'}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis
            dataKey="strike"
            tick={{ fontSize: 10, fill: 'var(--color-text-muted, #9ca3af)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'var(--color-text-muted, #9ca3af)' }}
            tickFormatter={(v: number) => (v / 1e6).toFixed(0) + 'M'}
            width={48}
          />
          <Tooltip
            contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 8 }}
            labelStyle={{ color: chartTheme.tooltip.text }}
            formatter={(v: any) => [(v / 1e6).toFixed(2) + 'M', 'Pain']}
          />
          <Bar dataKey="pain" fill="#6366f1" radius={[2, 2, 0, 0]} />
          {data.max_pain != null && (
            <ReferenceLine x={data.max_pain} stroke="#f59e0b" strokeWidth={2} strokeDasharray="4 2" />
          )}
          {data.spot_price != null && (
            <ReferenceLine x={data.spot_price} stroke="#60a5fa" strokeWidth={2} strokeDasharray="4 2" />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
