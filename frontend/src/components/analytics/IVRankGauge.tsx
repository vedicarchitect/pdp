import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'

interface Props {
  underlying: string
}

export function IVRankGauge({ underlying }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['iv-history', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/iv-history`)
      if (!res.ok) throw new Error('Failed to fetch IV history')
      return res.json()
    },
    refetchInterval: 300000, // 5 mins
  })

  if (isLoading) {
    return <Card className="p-4 text-center text-text-muted rounded-xl h-full flex items-center justify-center">Loading IV...</Card>
  }

  if (!data || data.lookback_days === 0) {
    return <Card className="p-4 text-center text-text-muted rounded-xl h-full flex items-center justify-center">No historical IV data.</Card>
  }

  if (data.iv_rank === null || data.iv_rank === undefined) {
    return (
      <Card className="p-4 rounded-xl h-full flex flex-col items-center justify-center gap-1">
        <span className="text-text-muted text-sm">Insufficient IV history</span>
        <span className="text-text-muted text-xs">{data.warning ?? `${data.lookback_days} days (need 20+)`}</span>
      </Card>
    )
  }

  const { current_iv, iv_rank, iv_percentile, iv_high, iv_low, lookback_days } = data

  const isHigh = iv_rank > 80
  const isLow = iv_rank < 20

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[200px]">
      <div className="p-4 border-b border-surface-border flex justify-between items-center shrink-0">
        <h3 className="text-sm font-semibold tracking-tight">Implied Volatility Context</h3>
        <Badge variant={isHigh ? 'danger' : isLow ? 'success' : 'outline'} className="text-[10px]">
          {isHigh ? 'High IV' : isLow ? 'Low IV' : 'Normal IV'}
        </Badge>
      </div>
      <div className="flex-1 p-5 flex flex-col justify-center">
        <div className="flex justify-between items-end mb-2">
          <div>
            <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-1">Current ATM IV</div>
            <div className="text-3xl font-mono font-bold tracking-tight">{current_iv.toFixed(2)}%</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-mono text-text-muted">Rank: <span className="text-text-main font-semibold">{iv_rank.toFixed(1)}</span></div>
            <div className="text-sm font-mono text-text-muted">Percentile: <span className="text-text-main font-semibold">{iv_percentile.toFixed(1)}</span></div>
          </div>
        </div>

        {/* Custom Gauge / Range Slider representation */}
        <div className="mt-4 relative pt-1">
          <div className="flex mb-1 items-center justify-between">
            <div className="text-[10px] font-mono text-text-muted">{iv_low.toFixed(1)}% (Low)</div>
            <div className="text-[10px] font-mono text-text-muted">{iv_high.toFixed(1)}% (High)</div>
          </div>
          <div className="overflow-hidden h-2 mb-4 text-xs flex rounded bg-surface border border-surface-border">
            <div style={{ width: `${iv_rank}%` }} className={`shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center ${isHigh ? 'bg-danger' : isLow ? 'bg-success' : 'bg-primary'}`}></div>
          </div>
          {/* Marker for current IV */}
          <div className="absolute top-6 -ml-1 border-solid border-t-8 border-t-primary border-x-4 border-x-transparent border-b-0 w-0 h-0" style={{ left: `${iv_rank}%` }}></div>
        </div>
        
        <div className="text-[10px] text-text-muted text-center mt-1">Based on {lookback_days} historical days</div>
      </div>
    </Card>
  )
}
