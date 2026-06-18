import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

interface Props {
  underlying: string
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload
    return (
      <div className="bg-surface border border-surface-border p-3 rounded-lg shadow-xl text-xs flex flex-col gap-1">
        <p className="font-semibold text-text-muted mb-1">{label}</p>
        <p className="font-mono text-warning font-bold">ATM {data.atm} Straddle: ₹{data.premium.toFixed(1)}</p>
        <p className="font-mono text-text-muted">CE: ₹{data.ce.toFixed(1)} | PE: ₹{data.pe.toFixed(1)}</p>
        <p className="font-mono text-text-muted">Spot: {data.spot.toFixed(2)}</p>
      </div>
    )
  }
  return null
}

export function StraddleHistoryChart({ underlying }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['straddle-history', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/straddle-history`)
      if (!res.ok) throw new Error('Failed to fetch straddle history')
      return res.json()
    },
    refetchInterval: 30000,
  })

  if (isLoading) {
    return <Card className="p-8 text-center text-text-muted rounded-xl h-[400px] flex items-center justify-center">Loading Straddle History...</Card>
  }

  const history = data?.history || []

  if (history.length === 0) {
    return <Card className="p-8 text-center text-text-muted rounded-xl h-[400px] flex items-center justify-center">No straddle history available for today.</Card>
  }

  const chartData = history.map((h: any) => ({
    time: new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    premium: h.straddle_premium,
    ce: h.ce_premium,
    pe: h.pe_premium,
    spot: h.spot,
    atm: h.atm_strike
  }))

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[400px]">
      <div className="p-4 border-b border-surface-border">
        <h3 className="text-sm font-semibold tracking-tight">ATM Straddle Premium History (Intraday)</h3>
      </div>
      <div className="flex-1 p-4">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="straddleColor" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" vertical={false} />
            <XAxis dataKey="time" stroke="#666" fontSize={12} tickMargin={10} minTickGap={30} />
            <YAxis stroke="#666" fontSize={12} domain={['dataMin - 10', 'dataMax + 10']} />
            <Tooltip content={<CustomTooltip />} />
            <Area 
              type="monotone" 
              dataKey="premium" 
              stroke="#f59e0b" 
              strokeWidth={2}
              fillOpacity={1} 
              fill="url(#straddleColor)" 
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
