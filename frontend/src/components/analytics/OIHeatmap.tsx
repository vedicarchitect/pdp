import { Fragment, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { Lock } from 'lucide-react'
import { chartTheme } from '@/lib/chartTheme'

interface Props {
  underlying: string
  expiry?: string
}

interface OIStrike {
  strike: number
  ce_oi: number
  pe_oi: number
  total_oi: number
}

interface Snapshot {
  ts: string
  pcr: number | null
  strikes: OIStrike[]
}

interface OIHistoryResponse {
  mode?: string
  snapshots: Snapshot[]
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

function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return ts
  }
}

export function OIHeatmap({ underlying, expiry }: Props) {
  const params = new URLSearchParams({ n: '40' })
  if (expiry) params.set('expiry', expiry)
  const url = `/api/v1/options/${underlying}/oi-history?${params}`

  const { data, isLoading } = useQuery<OIHistoryResponse>({
    queryKey: ['options-oi-history', underlying, expiry],
    queryFn: () => fetch(url).then((r) => r.json()),
    refetchInterval: 30_000,
  })

  if (isLoading) return <LoadingSkeleton />
  if (!data || data.mode === 'paper') return <PaperModePlaceholder />

  const { snapshots } = data
  if (snapshots.length === 0) return <PaperModePlaceholder />

  // Pre-compute O(1) lookup for strikes to avoid O(N*M*K) find() in render loop
  const { allStrikes, colMaxOI, strikeOIMap } = useMemo(() => {
    const strikes = new Set<number>()
    const maxOI = new Array<number>(snapshots.length)
    const map = new Map<number, Map<number, number>>()

    snapshots.forEach((snap, ci) => {
      let currentMax = 1
      const snapMap = new Map<number, number>()
      snap.strikes.forEach((s) => {
        strikes.add(s.strike)
        currentMax = Math.max(currentMax, s.total_oi)
        snapMap.set(s.strike, s.total_oi)
      })
      maxOI[ci] = currentMax
      map.set(ci, snapMap)
    })

    return {
      allStrikes: Array.from(strikes).sort((a, b) => b - a),
      colMaxOI: maxOI,
      strikeOIMap: map,
    }
  }, [snapshots])

  // PCR line data
  const pcrData = snapshots.map((snap) => ({
    ts: formatTs(snap.ts),
    pcr: snap.pcr,
  }))

  return (
    <div className="flex flex-col gap-4">
      {/* Heatmap */}
      <div className="overflow-x-auto">
        <div
          className="grid text-[10px]"
          style={{
            gridTemplateColumns: `56px repeat(${snapshots.length}, minmax(20px, 1fr))`,
            minWidth: snapshots.length * 20 + 56,
          }}
        >
          {/* Header row */}
          <div className="text-text-muted px-1 py-0.5">Strike</div>
          {snapshots.map((snap, ci) => (
            <div key={ci} className="text-center text-text-muted px-0.5 py-0.5 truncate">
              {ci % Math.max(1, Math.floor(snapshots.length / 6)) === 0
                ? formatTs(snap.ts)
                : ''}
            </div>
          ))}

          {/* Data rows */}
          {allStrikes.map((strike) => (
            <Fragment key={strike}>
              <div className="text-text-muted px-1 py-0.5 font-mono">
                {strike}
              </div>
              {snapshots.map((snap, ci) => {
                const oi = strikeOIMap.get(ci)?.get(strike) ?? 0
                const opacity = oi / colMaxOI[ci]
                return (
                  <div
                    key={`${strike}-${ci}`}
                    title={`Strike ${strike} @ ${formatTs(snap.ts)}: OI ${oi.toLocaleString()}`}
                    className="h-5"
                    style={{
                      background: `rgba(251,191,36,${opacity.toFixed(3)})`,
                      border: '1px solid rgba(255,255,255,0.04)',
                    }}
                  />
                )
              })}
            </Fragment>
          ))}
        </div>
      </div>

      {/* PCR line chart */}
      <div>
        <div className="text-xs text-text-muted mb-1">PCR over time</div>
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={pcrData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              dataKey="ts"
              tick={{ fontSize: 9, fill: 'var(--color-text-muted, #9ca3af)' }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 9, fill: 'var(--color-text-muted, #9ca3af)' }}
              width={32}
            />
            <Tooltip
              contentStyle={{ background: chartTheme.tooltip.bg, border: `1px solid ${chartTheme.tooltip.border}`, borderRadius: 8 }}
              formatter={(v: any) => [Number(v)?.toFixed(2) ?? '—', 'PCR']}
              labelStyle={{ color: chartTheme.tooltip.text }}
            />
            <Line
              type="monotone"
              dataKey="pcr"
              stroke="#a78bfa"
              dot={false}
              strokeWidth={1.5}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
