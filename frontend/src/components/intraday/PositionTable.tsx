import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { OrderEntry } from '@/components/orders/OrderEntry'
import type { Position, StrategyGroup } from '../../types/intraday'

interface Props {
  positions: Position[]
}

function pnlColor(value: number): string {
  if (value > 0) return 'text-bullish'
  if (value < 0) return 'text-bearish'
  return 'text-text-muted'
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

function LegRow({ pos, onClose }: { pos: Position, onClose: (pos: Position) => void }) {
  const totalPnl = pos.realized_pnl + pos.unrealized_pnl
  const prevLtpRef = useRef<number | null>(null)
  const [ltpFlash, setLtpFlash] = useState('')

  useEffect(() => {
    const prev = prevLtpRef.current
    const curr = pos.ltp ?? null
    if (prev !== null && curr !== null && curr !== prev) {
      const cls = curr > prev ? 'animate-flash-bullish' : 'animate-flash-bearish'
      setLtpFlash(cls)
      const timer = setTimeout(() => setLtpFlash(''), 800)
      prevLtpRef.current = curr
      return () => clearTimeout(timer)
    }
    prevLtpRef.current = curr
  }, [pos.ltp])

  return (
    <tr className="bg-surface/50 border-t border-surface-border text-xs text-text-muted hover:bg-surface-hover transition-colors">
      <td className="pl-8 py-2 font-mono text-text-main">{pos.security_id}</td>
      <td className="py-2 text-center text-text-main font-medium">{pos.net_qty}</td>
      <td className="py-2 text-right font-mono">{fmt(pos.avg_price)}</td>
      <td className={`py-2 text-right font-mono transition-colors ${ltpFlash}`}>
        {pos.ltp != null ? fmt(pos.ltp) : '—'}
      </td>
      <td className="py-2 text-right font-mono text-text-muted/70">{pos.delta != null ? fmt(pos.delta, 3) : '—'}</td>
      <td className="py-2 text-right font-mono text-text-muted/70">{pos.gamma != null ? fmt(pos.gamma, 4) : '—'}</td>
      <td className="py-2 text-right font-mono text-text-muted/70">{pos.theta != null ? fmt(pos.theta, 3) : '—'}</td>
      <td className="py-2 text-right font-mono text-text-muted/70">{pos.vega != null ? fmt(pos.vega, 3) : '—'}</td>
      <td className={`py-2 text-right font-mono ${pnlColor(totalPnl)}`}>{fmt(totalPnl)}</td>
      <td className="py-2 pr-4 text-right">
        {pos.net_qty !== 0 && (
          <Button
            variant="secondary"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              onClose(pos)
            }}
          >
            Close
          </Button>
        )}
      </td>
    </tr>
  )
}

function StrategyRow({ group, expanded, onToggle }: { group: StrategyGroup; expanded: boolean; onToggle: () => void }) {
  return (
    <tr
      className="border-t border-surface-border cursor-pointer hover:bg-surface-hover transition-colors focus-visible:outline-none focus-visible:bg-surface-hover"
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onToggle()
        }
      }}
      tabIndex={0}
      aria-expanded={expanded}
    >
      <td className="px-4 py-3 font-medium flex items-center gap-2 text-text-main">
        <span className="text-text-muted text-xs transition-transform duration-200" style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
        {group.strategy_id}
        <span className="text-xs text-text-muted/70 ml-1">({group.positions.length} leg{group.positions.length !== 1 ? 's' : ''})</span>
      </td>
      <td className="py-3 text-center text-text-muted">—</td>
      <td className="py-2" />
      <td className="py-2" />
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_delta)}`}>{fmt(group.total_delta, 3)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_gamma)}`}>{fmt(group.total_gamma, 4)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_theta)}`}>{fmt(group.total_theta, 3)}</td>
      <td className={`py-2 text-right font-mono text-sm ${pnlColor(group.total_vega)}`}>{fmt(group.total_vega, 3)}</td>
      <td className={`py-2 text-right font-mono font-semibold ${pnlColor(group.total_pnl)}`}>{fmt(group.total_pnl)}</td>
      <td className="py-2"></td>
    </tr>
  )
}

const COLUMNS = ['Security / Strategy', 'Qty', 'Avg', 'LTP', 'Δ', 'Γ', 'Θ', 'Vega', 'P&L', 'Action']

export function PositionTable({ positions }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [closePosSecurity, setClosePosSecurity] = useState<{ id: string, side: "BUY" | "SELL", qty: number } | null>(null)
  const groups = useMemo(() => groupPositions(positions.filter((p) => p.net_qty !== 0)), [positions])

  if (groups.length === 0) {
    return (
      <div className="text-center text-text-subtle py-12 text-sm">
        No open positions
      </div>
    )
  }

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  return (
    <Card className="overflow-x-auto rounded-xl">
      <table className="w-full text-sm text-left">
        <thead className="bg-surface text-xs text-text-muted uppercase tracking-wider font-semibold border-b border-surface-border">
          <tr>
            {COLUMNS.map((col) => (
              <th key={col} className={`px-4 py-3 ${col === 'P&L' || col === 'Δ' || col === 'Γ' || col === 'Θ' || col === 'Vega' ? 'text-right' : ''}`}>
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-border">
          {groups.map((group) => (
            <React.Fragment key={group.strategy_id}>
              <StrategyRow
                group={group}
                expanded={expanded.has(group.strategy_id)}
                onToggle={() => toggle(group.strategy_id)}
              />
              {expanded.has(group.strategy_id) && group.positions.map((pos) => (
                <LegRow 
                  key={`${pos.security_id}-${pos.product}`} 
                  pos={pos} 
                  onClose={(p) => setClosePosSecurity({
                    id: p.security_id,
                    side: p.net_qty > 0 ? "SELL" : "BUY",
                    qty: Math.abs(p.net_qty)
                  })}
                />
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>

      {closePosSecurity && (
        <OrderEntry
          open={!!closePosSecurity}
          onOpenChange={(open) => !open && setClosePosSecurity(null)}
          prefill={{
            security_id: closePosSecurity.id,
            side: closePosSecurity.side,
            qty: closePosSecurity.qty,
            order_type: "MARKET",
          }}
        />
      )}
    </Card>
  )
}
