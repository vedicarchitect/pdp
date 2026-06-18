import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Tooltip } from '@/components/ui/Tooltip'
import type { PayoffResult } from '../../types/builder'

interface Props {
  result: PayoffResult | null
  isLoading: boolean
}

function Metric({ label, value, colored = false }: { label: string; value: React.ReactNode; colored?: boolean }) {
  const isPositive = typeof value === 'string' ? value.includes('+') || (!value.includes('-') && value !== '0') : Number(value) > 0
  const isNegative = typeof value === 'string' ? value.includes('-') : Number(value) < 0
  
  return (
    <div className="flex flex-col gap-1 p-3 bg-surface/50 rounded-lg">
      <span className="text-[11px] font-medium text-text-muted uppercase tracking-wider">{label}</span>
      <span className={`text-sm font-mono font-bold ${colored ? (isPositive ? 'text-bullish' : isNegative ? 'text-bearish' : 'text-text-main') : 'text-text-main'}`}>
        {value}
      </span>
    </div>
  )
}

export function GreeksPanel({ result, isLoading }: Props) {
  if (isLoading) {
    return <Card className="p-4 rounded-xl text-text-muted text-sm text-center">Calculating payoff...</Card>
  }

  if (!result) return null

  const pop = (result.probability_of_profit * 100).toFixed(1)
  const maxP = result.max_profit === null ? 'Unlimited' : `₹${result.max_profit.toFixed(2)}`
  const maxL = result.max_loss === null ? 'Unlimited' : `₹${result.max_loss.toFixed(2)}`
  const margin = result.margin_estimate ? `₹${result.margin_estimate.toFixed(2)}${result.margin_is_approximate ? ' ≈' : ''}` : '₹0.00'

  return (
    <Card className="rounded-xl overflow-hidden flex flex-col h-full">
      <div className="p-4 border-b border-surface-border">
        <h3 className="text-sm font-semibold tracking-tight">Greeks & Analysis</h3>
      </div>
      <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3 flex-1 overflow-y-auto">
        <Metric label="Net Delta" value={result.net_greeks.delta.toFixed(4)} colored />
        <Metric label="Net Gamma" value={result.net_greeks.gamma.toFixed(4)} colored />
        <Metric label="Net Theta" value={result.net_greeks.theta.toFixed(2)} colored />
        <Metric label="Net Vega" value={result.net_greeks.vega.toFixed(2)} colored />
        
        <div className="col-span-2 md:col-span-4 h-px bg-surface-border my-1" />
        
        <Metric label="Max Profit" value={maxP} colored={result.max_profit !== null} />
        <Metric label="Max Loss" value={maxL} colored={result.max_loss !== null} />
        <Metric label="Prob of Profit" value={`${pop}%`} />
        <Metric label="Est. Margin" value={margin} />
        
        <div className="col-span-2 md:col-span-4 mt-1">
          <span className="text-[11px] font-medium text-text-muted uppercase tracking-wider block mb-2">Breakevens</span>
          <div className="flex flex-wrap gap-2">
            {result.breakevens.length > 0 ? result.breakevens.map(be => (
              <Badge key={be} variant="warning" className="font-mono">{be.toFixed(2)}</Badge>
            )) : <span className="text-sm text-text-muted">None</span>}
          </div>
        </div>
      </div>
      <div className="p-4 bg-surface/30 border-t border-surface-border flex justify-end">
        <Tooltip content="Order entry coming soon (Proposal #6)">
          <div>
            <Button disabled className="w-full sm:w-auto font-semibold">
              Trade This Strategy
            </Button>
          </div>
        </Tooltip>
      </div>
    </Card>
  )
}
