import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import type { PayoffLeg } from '../../types/builder'

interface Props {
  underlying: string
  onAddLeg: (leg: Omit<PayoffLeg, 'id'>) => void
}

export function ChainPicker({ underlying, onAddLeg }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['chain', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/chain`)
      if (!res.ok) throw new Error('Failed to fetch chain')
      return res.json()
    },
  })

  if (isLoading) {
    return <Card className="p-8 text-center text-text-muted rounded-xl">Loading chain...</Card>
  }

  if (!data?.strikes || data.strikes.length === 0) {
    return <Card className="p-8 text-center text-text-muted rounded-xl">No chain data available.</Card>
  }

  const spot = data.spot_price || 0
  const expiry = data.expiry || ''

  // Pick a subset of strikes around ATM (±10 strikes)
  const atmIdx = data.strikes.findIndex((s: any) => s.strike >= spot)
  const startIdx = Math.max(0, atmIdx - 10)
  const endIdx = Math.min(data.strikes.length, atmIdx + 11)
  const viewStrikes = data.strikes.slice(startIdx, endIdx)

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[400px]">
      <div className="p-3 border-b border-surface-border bg-surface flex justify-between items-center shrink-0">
        <div className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Option Chain
        </div>
        <div className="text-xs text-text-muted font-mono">Spot: {spot.toFixed(2)}</div>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs text-center">
          <thead className="bg-surface/50 text-text-muted sticky top-0 border-b border-surface-border">
            <tr>
              <th className="py-2 px-2 border-r border-surface-border" colSpan={2}>CALLS</th>
              <th className="py-2 px-2 bg-surface font-semibold tracking-wider w-20">STRIKE</th>
              <th className="py-2 px-2 border-l border-surface-border" colSpan={2}>PUTS</th>
            </tr>
            <tr className="border-b border-surface-border">
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal">IV</th>
              <th className="py-1 px-2 border-r border-surface-border font-normal">LTP</th>
              <th className="py-1 px-2 bg-surface"></th>
              <th className="py-1 px-2 border-r border-surface-border/50 border-l border-surface-border font-normal">LTP</th>
              <th className="py-1 px-2 font-normal">IV</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border/50">
            {viewStrikes.map((s: any) => {
              const ceItm = s.strike < spot
              const peItm = s.strike > spot
              
              const cePremium = s.ce?.last_price || 0
              const ceIv = s.ce?.iv || 0.2
              
              const pePremium = s.pe?.last_price || 0
              const peIv = s.pe?.iv || 0.2

              return (
                <tr key={s.strike} className="hover:bg-surface/30">
                  <td className={`py-1.5 px-2 border-r border-surface-border/50 ${ceItm ? 'bg-primary/5' : ''}`}>
                    {(ceIv * 100).toFixed(1)}
                  </td>
                  <td 
                    className={`py-1.5 px-2 border-r border-surface-border cursor-pointer hover:bg-primary/20 transition-colors ${ceItm ? 'bg-primary/5' : ''}`}
                    onClick={() => onAddLeg({ strike: s.strike, expiry, option_type: 'CE', side: 'BUY', lots: 1, premium: cePremium, iv: ceIv, delta: s.ce?.delta||0, gamma: s.ce?.gamma||0, theta: s.ce?.theta||0, vega: s.ce?.vega||0 })}
                    title="Click to add CE leg"
                  >
                    <span className="font-mono">{cePremium.toFixed(1)}</span>
                  </td>
                  <td className="py-1.5 px-2 font-semibold font-mono bg-surface relative">
                    {Math.abs(s.strike - spot) < (s.strike * 0.005) && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-3/4 bg-warning rounded-r-sm" />
                    )}
                    {s.strike}
                  </td>
                  <td 
                    className={`py-1.5 px-2 border-l border-surface-border border-r border-surface-border/50 cursor-pointer hover:bg-primary/20 transition-colors ${peItm ? 'bg-primary/5' : ''}`}
                    onClick={() => onAddLeg({ strike: s.strike, expiry, option_type: 'PE', side: 'BUY', lots: 1, premium: pePremium, iv: peIv, delta: s.pe?.delta||0, gamma: s.pe?.gamma||0, theta: s.pe?.theta||0, vega: s.pe?.vega||0 })}
                    title="Click to add PE leg"
                  >
                    <span className="font-mono">{pePremium.toFixed(1)}</span>
                  </td>
                  <td className={`py-1.5 px-2 ${peItm ? 'bg-primary/5' : ''}`}>
                    {(peIv * 100).toFixed(1)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
