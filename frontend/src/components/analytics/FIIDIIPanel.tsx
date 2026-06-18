import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'

export function FIIDIIPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['fii-dii'],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/fii-dii`)
      if (!res.ok) throw new Error('Failed to fetch FII/DII data')
      return res.json()
    },
    refetchInterval: 3600000, // 1 hour
  })

  if (isLoading) {
    return <Card className="p-4 text-center text-text-muted rounded-xl h-full flex items-center justify-center">Loading FII/DII Data...</Card>
  }

  // If the backend stub is active, it returns available: false
  if (!data || !data.available) {
    return null
  }

  const dii = data.data

  const Metric = ({ label, value }: { label: string, value: number }) => (
    <div className="flex justify-between items-center py-1">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={`text-sm font-mono font-semibold ${value > 0 ? 'text-bullish' : value < 0 ? 'text-bearish' : 'text-text-main'}`}>
        {value > 0 ? '+' : ''}{value.toFixed(1)} Cr
      </span>
    </div>
  )

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[200px]">
      <div className="p-4 border-b border-surface-border flex justify-between items-center shrink-0">
        <h3 className="text-sm font-semibold tracking-tight">Institutional Net Flows</h3>
        <Badge variant="outline" className="text-[10px]">{dii.date}</Badge>
      </div>
      <div className="p-4 flex-1 grid grid-cols-2 gap-6 overflow-y-auto">
        <div>
          <h4 className="text-[11px] font-bold text-text-muted uppercase tracking-wider mb-2 border-b border-surface-border pb-1">FII Net</h4>
          <Metric label="Index Futures" value={dii.fii_index_futures_net} />
          <Metric label="Index Options" value={dii.fii_index_options_net} />
          <Metric label="Stock Futures" value={dii.fii_stock_futures_net} />
        </div>
        <div>
          <h4 className="text-[11px] font-bold text-text-muted uppercase tracking-wider mb-2 border-b border-surface-border pb-1">DII Net</h4>
          <Metric label="Index Futures" value={dii.dii_index_futures_net} />
          <Metric label="Index Options" value={dii.dii_index_options_net} />
          <Metric label="Stock Futures" value={dii.dii_stock_futures_net} />
        </div>
      </div>
    </Card>
  )
}
