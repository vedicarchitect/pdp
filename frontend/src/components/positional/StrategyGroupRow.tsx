import { useState } from 'react'
import type { StrategyGroup } from '../../types/positional'
import { LegRow } from './LegRow'

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function pnlClass(v: number) {
  return v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-gray-400'
}

interface Props {
  group: StrategyGroup
}

export function StrategyGroupRow({ group }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-t border-gray-700 hover:bg-gray-800 cursor-pointer select-none focus-visible:outline-none focus-visible:bg-gray-700"
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
        <td className="px-3 py-2.5 font-medium text-white flex items-center gap-2">
          <span className="text-gray-500 text-xs w-4">{expanded ? '▼' : '▶'}</span>
          {group.strategy_id}
          <span className="text-xs text-gray-500 font-normal ml-1">{group.legs.length} leg{group.legs.length !== 1 ? 's' : ''}</span>
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-gray-300">{fmt(group.net_delta, 3)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-gray-300">{fmt(group.net_gamma, 4)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-gray-300">{fmt(group.net_theta, 2)}</td>
        <td className="px-3 py-2.5 text-right font-mono text-gray-300">{fmt(group.net_vega, 2)}</td>
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
