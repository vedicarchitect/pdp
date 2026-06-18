import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  Cell,
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

interface GEXStrike {
  strike: number
  gex: number
}

interface GEXResponse {
  mode?: string
  per_strike: GEXStrike[]
  net_gex: number
  net_gex_cr: number
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

function formatNetGex(cr: number): string {
  const sign = cr >= 0 ? '+' : ''
  return `Net GEX: ${sign}₹${cr.toFixed(2)} Cr`
}

export function GEXChart({ underlying, expiry }: Props) {
  const params = new URLSearchParams()
  if (expiry) params.set('expiry', expiry)
  const url = `/api/v1/options/${underlying}/gex${params.size ? '?' + params : ''}`

  const { data, isLoading } = useQuery<GEXResponse>({
    queryKey: ['options-gex', underlying, expiry],
    queryFn: () => fetch(url).then((r) => r.json()),
    refetchInterval: 30_000,
  })

  if (isLoading) return <LoadingSkeleton />
  if (!data || data.mode === 'paper') return <PaperModePlaceholder />

  const netCr = data.net_gex_cr ?? 0
  const isPositive = netCr >= 0

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span
          className={`text-sm font-semibold px-2 py-0.5 rounded-md ${
            isPositive
              ? 'text-emerald-400 bg-emerald-400/10'
              : 'text-red-400 bg-red-400/10'
          }`}
        >
          {formatNetGex(netCr)}
        </span>
        <span className="text-xs text-text-muted">
          {isPositive ? 'Dealers long γ — stabilising' : 'Dealers short γ — destabilising'}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data.per_strike} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis
            dataKey="strike"
            tick={{ fontSize: 10, fill: 'var(--color-text-muted, #9ca3af)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'var(--color-text-muted, #9ca3af)' }}
            tickFormatter={(v: number) => (v / 1e9).toFixed(1) + 'B'}
            width={52}
          />
          <Tooltip
            contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 8 }}
            labelStyle={{ color: chartTheme.axis.color }}
            formatter={(v: any) => [(v / 1e9).toFixed(3) + 'B', 'Gamma']}
          />
          <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
          <Bar dataKey="gex" radius={[2, 2, 0, 0]}>
            {data.per_strike.map((entry, idx) => (
              <Cell
                key={idx}
                fill={entry.gex >= 0 ? '#34d399' : '#f87171'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
