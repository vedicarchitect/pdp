import React, { useMemo, useState } from 'react'
import type { Position, StrategyGroup } from '../../types/intraday'

interface Props {
  positions: Position[]
}

function pnlColor(value: number): string {
  if (value > 0) return 'text-green-400'
  if (value < 0) return 'text-red-400'
  return 'text-gray-400'
}

function fmt(n: number, decimals = 2): string {
  return n.toFixed(decimals)
}

function groupPositions(positions: Position[]): StrategyGroup[] {
  const map = new Map<string, Position[]>()
  for (const pos of positions) {
    const key = pos.strategy_id ?? 'Ungrouped'
    const arr = map.get(key) ?? []
    arr.push(pos)
    map.set(key, arr)
  }
  return Array.from(map.entries()).map(([strategy_id, legs]) => ({
    strategy_id,
    positions: legs,
    total_delta: legs.reduce((s, p) => s + (p.delta ?? 0) * p.net_qty, 0),
    total_gamma: legs.reduce((s, p) => s + (p.gamma ?? 0) * p.net_qty, 0),
    total_theta: legs.reduce((s, p) => s + (p.theta ?? 0) * p.net_qty, 0),
    total_vega: legs.reduce((s, p) => s + (p.vega ?? 0) * p.net_qty, 0),
    total_pnl: legs.reduce((s, p) => s + p.realized_pnl + p.unrealized_pnl, 0),
    realized_pnl: legs.reduce((s, p) => s + p.realized_pnl, 0),
    unrealized_pnl: legs.reduce((s, p) => s + p.unrealized_pnl, 0),
  }))
}

const LegRow = React.memo(function LegRow({ pos }: { pos: Position }) {
  const totalPnl = pos.realized_pnl + pos.unrealized_pnl
  return (
    <tr className="bg-gray-850 border-t border-gray-800 text-xs text-gray-400">
      <td className="pl-8 py-1.5 font-mono">{pos.security_id}</td>
      <td className="py-1.5 text-center">{pos.net_qty}</td>
      <td className="py-1.5 text-right font-mono">{fmt(pos.avg_price)}</td>
      <td className="py-1.5 text-right font-mono">{pos.ltp != null ? fmt(pos.ltp) : '—'}</td>
      <td className="py-1.5 text-right font-mono text-gray-500">{pos.delta != null ? fmt(pos.delta, 3) : '—'}</td>
      <td className="py-1.5 text-right font-mono text-gray-500">{pos.gamma != null ? fmt(pos.gamma, 4) : '—'}</td>
      <td className="py-1.5 text-right font-mono text-gray-500">{pos.theta != null ? fmt(pos.theta, 3) : '—'}</td>
      <td className="py-1.5 text-right font-mono text-gray-500">{pos.vega != null ? fmt(pos.vega, 3) : '—'}</td>
      <td className={`py-1.5 text-right font-mono ${pnlColor(totalPnl)}`}>{fmt(totalPnl)}</td>
    </tr>
  )
}, (prevProps, nextProps) => {
  return prevProps.pos.ltp === nextProps.pos.ltp &&
         prevProps.pos.realized_pnl === nextProps.pos.realized_pnl &&
         prevProps.pos.unrealized_pnl === nextProps.pos.unrealized_pnl &&
         prevProps.pos.net_qty === nextProps.pos.net_qty &&
         prevProps.pos.avg_price === nextProps.pos.avg_price &&
         prevProps.pos.security_id === nextProps.pos.security_id &&
         prevProps.pos.delta === nextProps.pos.delta &&
         prevProps.pos.gamma === nextProps.pos.gamma &&
         prevProps.pos.theta === nextProps.pos.theta &&
         prevProps.pos.vega === nextProps.pos.vega
})

const StrategyRow = React.memo(function StrategyRow({ group, expanded, onToggle }: { group: StrategyGroup; expanded: boolean; onToggle: (id: string) => void }) {
  const handleToggle = () => onToggle(group.strategy_id)

  return (
    <tr
      className="border-t border-gray-700 cursor-pointer hover:bg-gray-800 transition-colors focus-visible:outline-none focus-visible:bg-gray-700"
      onClick={handleToggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleToggle()
        }
      }}
      tabIndex={0}
      aria-expanded={expanded}
    >
      <td className="px-4 py-2 font-medium flex items-center gap-2">
        <span className="text-gray-500 text-xs">{expanded ? '▼' : '▶'}</span>
        {group.strategy_id}
        <span className="text-xs text-gray-600 ml-1">({group.positions.length} leg{group.positions.length !== 1 ? 's' : ''})</span>
      </td>
      <td className="py-2 text-center text-gray-500">—</td>
      <td className="py-2" />
      <td className="py-2" />
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_delta)}`}>{fmt(group.total_delta, 3)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_gamma)}`}>{fmt(group.total_gamma, 4)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_theta)}`}>{fmt(group.total_theta, 3)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_vega)}`}>{fmt(group.total_vega, 3)}</td>
      <td className={`py-2 text-right font-mono font-semibold ${pnlColor(group.total_pnl)}`}>{fmt(group.total_pnl)}</td>
    </tr>
  )
}, (prevProps, nextProps) => {
  return prevProps.expanded === nextProps.expanded &&
         prevProps.onToggle === nextProps.onToggle &&
         prevProps.group.total_pnl === nextProps.group.total_pnl &&
         prevProps.group.total_delta === nextProps.group.total_delta &&
         prevProps.group.total_gamma === nextProps.group.total_gamma &&
         prevProps.group.total_theta === nextProps.group.total_theta &&
         prevProps.group.total_vega === nextProps.group.total_vega &&
         prevProps.group.positions.length === nextProps.group.positions.length
})

const COLUMNS = ['Security / Strategy', 'Qty', 'Avg', 'LTP', 'Δ', 'Γ', 'Θ', 'Vega', 'P&L']

export function PositionTable({ positions }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const groups = useMemo(() => groupPositions(positions.filter((p) => p.net_qty !== 0)), [positions])

  if (groups.length === 0) {
    return (
      <div className="text-center text-gray-600 py-12 text-sm">
        No open positions
      </div>
    )
  }

  // Stable toggle reference to pass to memoized children
  const toggle = React.useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  return (
    <div className="overflow-x-auto rounded border border-gray-800">
      <table className="w-full text-sm text-left">
        <thead className="bg-gray-900 text-xs text-gray-500 uppercase tracking-wide">
          <tr>
            {COLUMNS.map((col) => (
              <th key={col} className={`px-4 py-2 ${col === 'P&L' || col === 'Δ' || col === 'Γ' || col === 'Θ' || col === 'Vega' ? 'text-right' : ''}`}>
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {groups.map((group) => (
            <React.Fragment key={group.strategy_id}>
              <StrategyRow
                group={group}
                expanded={expanded.has(group.strategy_id)}
                onToggle={toggle}
              />
              {expanded.has(group.strategy_id) && group.positions.map((pos) => (
                <LegRow key={`${pos.security_id}-${pos.product}`} pos={pos} />
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
