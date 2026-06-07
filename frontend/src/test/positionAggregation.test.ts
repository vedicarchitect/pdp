import { describe, it, expect } from 'vitest'
import type { Position } from '../types/intraday'

// Re-implement groupPositions here for unit testing (mirrors PositionTable internal)
function groupPositions(positions: Position[]) {
  const map = new Map<string, Position[]>()
  for (const pos of positions) {
    if (pos.net_qty === 0) continue
    const key = pos.strategy_id ?? 'Ungrouped'
    const arr = map.get(key) ?? []
    arr.push(pos)
    map.set(key, arr)
  }
  return Array.from(map.entries()).map(([strategy_id, legs]) => ({
    strategy_id,
    positions: legs,
    total_delta: legs.reduce((s, p) => s + (p.delta ?? 0) * p.net_qty, 0),
    total_pnl: legs.reduce((s, p) => s + p.realized_pnl + p.unrealized_pnl, 0),
    realized_pnl: legs.reduce((s, p) => s + p.realized_pnl, 0),
    unrealized_pnl: legs.reduce((s, p) => s + p.unrealized_pnl, 0),
  }))
}

const makePos = (overrides: Partial<Position> = {}): Position => ({
  security_id: 'NIFTY-25JUL-24000-CE',
  exchange_segment: 'NSE_FO',
  product: 'INTRADAY',
  net_qty: 50,
  avg_price: 100,
  realized_pnl: 0,
  unrealized_pnl: 500,
  updated_at: new Date().toISOString(),
  ...overrides,
})

describe('P&L aggregation', () => {
  it('groups positions by strategy_id', () => {
    const positions = [
      makePos({ strategy_id: 'strangle-1', security_id: 'CE' }),
      makePos({ strategy_id: 'strangle-1', security_id: 'PE' }),
      makePos({ strategy_id: 'trend-1', security_id: 'FUT' }),
    ]
    const groups = groupPositions(positions)
    expect(groups).toHaveLength(2)
    expect(groups.find((g) => g.strategy_id === 'strangle-1')?.positions).toHaveLength(2)
  })

  it('falls back to Ungrouped when no strategy_id', () => {
    const positions = [makePos({ strategy_id: undefined })]
    const groups = groupPositions(positions)
    expect(groups[0].strategy_id).toBe('Ungrouped')
  })

  it('sums P&L across legs', () => {
    const positions = [
      makePos({ strategy_id: 'A', realized_pnl: 1000, unrealized_pnl: -200 }),
      makePos({ strategy_id: 'A', realized_pnl: 500, unrealized_pnl: 100 }),
    ]
    const groups = groupPositions(positions)
    expect(groups[0].total_pnl).toBe(1400) // 1000 - 200 + 500 + 100
  })

  it('excludes zero-qty positions', () => {
    const positions = [
      makePos({ net_qty: 0, strategy_id: 'A' }),
      makePos({ net_qty: 50, strategy_id: 'A' }),
    ]
    const groups = groupPositions(positions)
    expect(groups[0].positions).toHaveLength(1)
  })

  it('aggregates delta weighted by net_qty', () => {
    const positions = [
      makePos({ strategy_id: 'A', net_qty: 50, delta: 0.5 }),
      makePos({ strategy_id: 'A', net_qty: -50, delta: -0.5 }),
    ]
    const groups = groupPositions(positions)
    // 0.5 * 50 + (-0.5 * -50) = 25 + 25 = 50
    expect(groups[0].total_delta).toBeCloseTo(50)
  })

  it('returns empty when all positions are flat', () => {
    const positions = [makePos({ net_qty: 0 })]
    const groups = groupPositions(positions)
    expect(groups).toHaveLength(0)
  })
})
