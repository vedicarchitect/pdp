import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { ArrowUpRight, ArrowDownRight, ArrowRight, ShoppingCart } from 'lucide-react'
import { OrderEntry } from '@/components/orders/OrderEntry'
import { useState } from 'react'

interface Props {
  underlying: string
}

function getBadgeVariant(classification: string) {
  switch (classification) {
    case 'long_buildup': return 'success'
    case 'short_covering': return 'info'
    case 'short_buildup': return 'danger'
    case 'long_unwinding': return 'warning'
    default: return 'outline'
  }
}

function formatClassification(classification: string) {
  return classification.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function TrendIcon({ change }: { change: number }) {
  if (change > 0) return <ArrowUpRight className="w-3 h-3 text-success inline ml-1" />
  if (change < 0) return <ArrowDownRight className="w-3 h-3 text-danger inline ml-1" />
  return <ArrowRight className="w-3 h-3 text-text-muted inline ml-1" />
}

export function OIBuildupPanel({ underlying }: Props) {
  const [selectedLeg, setSelectedLeg] = useState<{ id: string, side: "BUY" | "SELL" } | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['oi-buildup', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/oi-buildup`)
      if (!res.ok) throw new Error('Failed to fetch buildup')
      return res.json()
    },
    refetchInterval: 30000,
  })

  if (isLoading) {
    return <Card className="p-8 text-center text-text-muted rounded-xl">Loading OI Buildup...</Card>
  }

  const buildup = data?.buildup || []

  if (buildup.length === 0) {
    return <Card className="p-8 text-center text-text-muted rounded-xl">No buildup data available (requires 2 snapshots).</Card>
  }

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-[500px]">
      <div className="p-4 border-b border-surface-border">
        <h3 className="text-sm font-semibold tracking-tight">OI Buildup (Since Last Snapshot)</h3>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs text-center">
          <thead className="bg-surface/50 text-text-muted sticky top-0 border-b border-surface-border">
            <tr>
              <th className="py-2 px-2 border-r border-surface-border" colSpan={3}>CALLS</th>
              <th className="py-2 px-2 bg-surface font-semibold tracking-wider w-20">STRIKE</th>
              <th className="py-2 px-2 border-l border-surface-border" colSpan={3}>PUTS</th>
            </tr>
            <tr className="border-b border-surface-border">
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal w-10"></th>
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal">Classification</th>
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal">OI Δ</th>
              <th className="py-1 px-2 border-r border-surface-border font-normal">Price Δ</th>
              
              <th className="py-1 px-2 bg-surface"></th>
              
              <th className="py-1 px-2 border-r border-surface-border/50 border-l border-surface-border font-normal">Price Δ</th>
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal">OI Δ</th>
              <th className="py-1 px-2 border-r border-surface-border/50 font-normal">Classification</th>
              <th className="py-1 px-2 font-normal w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border/50">
            {buildup.map((s: any) => (
              <tr key={s.strike} className="hover:bg-surface/30 group">
                <td className="py-1.5 px-2 border-r border-surface-border/50 text-center">
                  {s.ce && (
                    <button 
                      onClick={() => setSelectedLeg({ id: s.ce.security_id || `${underlying}_${s.strike}_CE`, side: "BUY" })}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-primary hover:text-bullish"
                      title="Buy Call"
                    >
                      <ShoppingCart className="w-3 h-3" />
                    </button>
                  )}
                </td>
                <td className="py-1.5 px-2 border-r border-surface-border/50">
                  {s.ce && <Badge variant={getBadgeVariant(s.ce.classification)} className="text-[10px]">{formatClassification(s.ce.classification)}</Badge>}
                </td>
                <td className="py-1.5 px-2 border-r border-surface-border/50 font-mono">
                  {s.ce ? `${s.ce.oi_change > 0 ? '+' : ''}${s.ce.oi_change} (${s.ce.oi_change_pct}%)` : '-'}
                </td>
                <td className="py-1.5 px-2 border-r border-surface-border font-mono">
                  {s.ce ? <>{s.ce.price_change}<TrendIcon change={s.ce.price_change} /></> : '-'}
                </td>
                
                <td className="py-1.5 px-2 font-semibold font-mono bg-surface">
                  {s.strike}
                </td>
                
                <td className="py-1.5 px-2 border-l border-surface-border border-r border-surface-border/50 font-mono">
                  {s.pe ? <>{s.pe.price_change}<TrendIcon change={s.pe.price_change} /></> : '-'}
                </td>
                <td className="py-1.5 px-2 border-r border-surface-border/50 font-mono">
                  {s.pe ? `${s.pe.oi_change > 0 ? '+' : ''}${s.pe.oi_change} (${s.pe.oi_change_pct}%)` : '-'}
                </td>
                <td className="py-1.5 px-2 border-r border-surface-border/50">
                  {s.pe && <Badge variant={getBadgeVariant(s.pe.classification)} className="text-[10px]">{formatClassification(s.pe.classification)}</Badge>}
                </td>
                <td className="py-1.5 px-2 text-center">
                  {s.pe && (
                    <button 
                      onClick={() => setSelectedLeg({ id: s.pe.security_id || `${underlying}_${s.strike}_PE`, side: "BUY" })}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-primary hover:text-bullish"
                      title="Buy Put"
                    >
                      <ShoppingCart className="w-3 h-3" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedLeg && (
        <OrderEntry
          open={!!selectedLeg}
          onOpenChange={(open) => !open && setSelectedLeg(null)}
          prefill={{
            security_id: selectedLeg.id,
            side: selectedLeg.side,
            order_type: "LIMIT",
          }}
        />
      )}
    </Card>
  )
}
