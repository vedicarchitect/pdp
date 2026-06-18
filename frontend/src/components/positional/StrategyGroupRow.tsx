import { useState } from 'react'
import type { StrategyGroup } from '../../types/positional'
import { LegRow } from './LegRow'

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function pnlClass(v: number) {
  return v > 0 ? 'text-bullish' : v < 0 ? 'text-bearish' : 'text-text-muted'
}

interface Props {
  group: StrategyGroup
}

export function StrategyGroupRow({ group }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-t border-surface-border hover:bg-surface-hover cursor-pointer select-none transition-colors focus-visible:outline-none focus-visible:bg-surface-hover"
        onClick={() => setExpanded((e) => !e)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setExpanded((ex) => !ex)
          }
        }}
        tabIndex={0}
        aria-expanded={expanded}
      >
        <td className="px-3 py-2.5 font-medium text-text-main flex items-center gap-2">
          <span className="text-text-subtle text-xs w-4 transition-transform duration-200" style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
          {group.strategy_id}
          <span className="text-xs text-text-subtle font-normal ml-1">{group.legs.length} leg{group.legs.length !== 1 ? 's' : ''}</span>
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted">{fmt(group.net_delta, 3)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted">{fmt(group.net_gamma, 4)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted">{fmt(group.net_theta, 2)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted">{fmt(group.net_vega, 2)}</td>
        <td className={`px-3 py-2.5 text-right font-mono font-semibold ${pnlClass(group.total_pnl)}`}>
          ₹{fmt(group.total_pnl)}
        </td>
        <td className={`px-3 py-2.5 text-right font-mono text-sm ${pnlClass(group.unrealized_pnl)}`}>
          ₹{fmt(group.unrealized_pnl)}
        </td>
        <td className={`px-3 py-2.5 text-right font-mono text-sm ${pnlClass(group.realized_pnl)}`}>
          ₹{fmt(group.realized_pnl)}
        </td>
      </tr>
      {expanded && group.legs.map((leg) => (
        <LegRow key={`${leg.security_id}-${leg.exchange_segment}`} leg={leg} />
      ))}
    </>
  )
}
