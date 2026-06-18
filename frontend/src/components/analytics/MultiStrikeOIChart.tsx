import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'

interface Props {
  underlying: string
}

export function MultiStrikeOIChart({ underlying }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['oi-series', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/oi-series?limit=50`)
      if (!res.ok) throw new Error('Failed to fetch oi series')
      return res.json()
    },
    refetchInterval: 30000,
  })

  if (isLoading) {
    return <Card className="p-8 text-center text-text-muted rounded-xl h-[400px] flex items-center justify-center">Loading Multi-Strike OI...</Card>
  }

  if (!data || !data.timestamps || data.timestamps.length === 0) {
    return <Card className="p-8 text-center text-text-muted rounded-xl h-[400px] flex items-center justify-center">No OI series data available.</Card>
  }

  const chartData = data.timestamps.map((ts: string, i: number) => {
    const point: any = { time: new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
    for (const [strike, series] of Object.entries(data.strikes)) {
      const s = series as any
      point[`${strike}_CE`] = s.ce_oi[i]
      point[`${strike}_PE`] = s.pe_oi[i]
    }
    return point
  })

  const strikes = Object.keys(data.strikes)
  // Define some colors for the strikes
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#f97316', '#64748b', '#84cc16']

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[500px]">
      <div className="p-4 border-b border-surface-border">
        <h3 className="text-sm font-semibold tracking-tight">Top Strikes OI Evolution</h3>
      </div>
      <div className="flex-1 p-4">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" vertical={false} />
            <XAxis dataKey="time" stroke="#666" fontSize={12} tickMargin={10} minTickGap={30} />
            <YAxis stroke="#666" fontSize={12} tickFormatter={(v) => (v / 100000).toFixed(1) + 'L'} />
            <Tooltip 
              contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333', borderRadius: '8px', fontSize: '12px' }}
              itemStyle={{ padding: '2px 0' }}
            />
            <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '20px' }} />
            
            {strikes.map((strike, idx) => (
              <Line 
                key={`${strike}_CE`} 
                type="monotone" 
                dataKey={`${strike}_CE`} 
                name={`${strike} CE`} 
                stroke={colors[idx % colors.length]} 
                strokeWidth={1.5}
                dot={false}
              />
            ))}
            {strikes.map((strike, idx) => (
              <Line 
                key={`${strike}_PE`} 
                type="monotone" 
                dataKey={`${strike}_PE`} 
                name={`${strike} PE`} 
                stroke={colors[idx % colors.length]} 
                strokeWidth={1.5}
                strokeDasharray="5 5"
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
