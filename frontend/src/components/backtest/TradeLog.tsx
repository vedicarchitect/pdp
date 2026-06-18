import { useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface LegDetail {
  type: string
  side: string
  strike: number
  lots: number
  entry_price: number
  exit_price: number
  pnl_points: number
}

interface TradeRow {
  date: string
  entry_time: string
  exit_time: string
  legs: LegDetail[]
  pnl: number
  exit_reason: string
  re_entry_count: number
}

function ExitReasonBadge({ reason }: { reason: string }) {
  const variants: Record<string, 'success' | 'danger' | 'warning' | 'info'> = {
    time_exit: 'info',
    combined_sl: 'danger',
    per_leg_sl: 'danger',
    trailing_sl: 'warning',
    combined_target: 'success',
  }
  const labels: Record<string, string> = {
    time_exit: 'Time',
    combined_sl: 'SL',
    per_leg_sl: 'Leg SL',
    trailing_sl: 'Trail SL',
    combined_target: 'Target',
  }
  return (
    <Badge variant={variants[reason] ?? 'default'} size="sm">
      {labels[reason] ?? reason}
    </Badge>
  )
}

function ExpandedLegs({ legs }: { legs: LegDetail[] }) {
  return (
    <div className="px-4 py-2 bg-surface-raised/30 border-t border-surface-border">
      <div className="grid grid-cols-6 gap-2 text-xs text-text-muted mb-1 font-medium">
        <span>Type</span><span>Side</span><span>Strike</span>
        <span>Entry</span><span>Exit</span><span>P&L pts</span>
      </div>
      {legs.map((leg, i) => (
        <div key={i} className="grid grid-cols-6 gap-2 text-xs text-text-main py-0.5">
          <span className="font-mono">{leg.type}</span>
          <span className={leg.side === 'SELL' ? 'text-bearish' : 'text-bullish'}>{leg.side}</span>
          <span className="font-mono">{leg.strike}</span>
          <span className="font-mono">₹{leg.entry_price.toFixed(2)}</span>
          <span className="font-mono">₹{leg.exit_price.toFixed(2)}</span>
          <span className={cn('font-mono', leg.pnl_points >= 0 ? 'text-bullish' : 'text-bearish')}>
            {leg.pnl_points >= 0 ? '+' : ''}{leg.pnl_points.toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  )
}

export function TradeLog({ data }: { data: TradeRow[] }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const toggle = (i: number) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  if (!data.length) {
    return <div className="text-sm text-text-muted text-center py-8">No trades</div>
  }

  return (
    <div className="border border-surface-border rounded-lg overflow-hidden">
      <div className="grid grid-cols-[32px_90px_70px_70px_100px_70px_1fr] gap-2 px-3 py-2 bg-surface-raised text-xs font-medium text-text-muted border-b border-surface-border">
        <span />
        <span>Date</span>
        <span>Entry</span>
        <span>Exit</span>
        <span>P&L</span>
        <span>Reason</span>
        <span>Re-entries</span>
      </div>
      {data.map((trade, i) => (
        <div key={i} className="border-b border-surface-border last:border-0">
          <div
            className="grid grid-cols-[32px_90px_70px_70px_100px_70px_1fr] gap-2 px-3 py-2 items-center cursor-pointer hover:bg-surface-raised/40 transition-colors"
            onClick={() => toggle(i)}
          >
            <span className="text-text-muted">
              {expanded.has(i) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
            <span className="font-mono text-xs text-text-muted">{trade.date}</span>
            <span className="font-mono text-xs text-text-main">{trade.entry_time}</span>
            <span className="font-mono text-xs text-text-main">{trade.exit_time}</span>
            <span className={cn('font-mono text-sm font-medium', trade.pnl >= 0 ? 'text-bullish' : 'text-bearish')}>
              {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
            <ExitReasonBadge reason={trade.exit_reason} />
            <span className="text-xs text-text-muted">{trade.re_entry_count || '—'}</span>
          </div>
          {expanded.has(i) && <ExpandedLegs legs={trade.legs} />}
        </div>
      ))}
    </div>
  )
}
