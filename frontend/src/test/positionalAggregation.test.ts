import { describe, it, expect } from 'vitest'
import type { PositionalLeg, StrategyGroup } from '../types/positional'

function makeGroup(legs: PositionalLeg[]): StrategyGroup {
  const netDelta = legs.reduce((s, l) => s + (l.greeks?.delta ?? 0) * l.net_qty, 0)
  const netGamma = legs.reduce((s, l) => s + (l.greeks?.gamma ?? 0) * l.net_qty, 0)
  const netTheta = legs.reduce((s, l) => s + (l.greeks?.theta ?? 0) * l.net_qty, 0)
  const netVega = legs.reduce((s, l) => s + (l.greeks?.vega ?? 0) * l.net_qty, 0)
  const unrealized = legs.reduce((s, l) => s + l.unrealized_pnl, 0)
  const realized = legs.reduce((s, l) => s + l.realized_pnl, 0)
  return {
    strategy_id: legs[0]?.strategy_id ?? 'test',
    legs,
    net_delta: netDelta,
    net_gamma: netGamma,
    net_theta: netTheta,
    net_vega: netVega,
    unrealized_pnl: unrealized,
    realized_pnl: realized,
    total_pnl: unrealized + realized,
  }
}

function makeLeg(overrides: Partial<PositionalLeg> = {}): PositionalLeg {
  return {
    security_id: 'NIFTY-24000-CE',
    exchange_segment: 'NSE_FO',
    product: 'CARRYFORWARD',
    net_qty: 50,
    avg_price: 200,
    realized_pnl: 0,
    unrealized_pnl: 1000,
    updated_at: new Date().toISOString(),
    strategy_id: 'iron-condor-1',
    ...overrides,
  }
}

describe('Positional Greek aggregation', () => {
  it('aggregates delta weighted by net_qty', () => {
    const legs = [
      makeLeg({ net_qty: 50, greeks: { delta: 0.4, gamma: 0.01, theta: -5, vega: 10 } }),
      makeLeg({ net_qty: -50, greeks: { delta: -0.3, gamma: 0.01, theta: -5, vega: 10 } }),
    ]
    const group = makeGroup(legs)
    // 0.4 * 50 + (-0.3 * -50) = 20 + 15 = 35
    expect(group.net_delta).toBeCloseTo(35)
  })

  it('aggregates gamma across legs', () => {
    const legs = [
      makeLeg({ net_qty: 50, greeks: { delta: 0.4, gamma: 0.02, theta: -5, vega: 10 } }),
      makeLeg({ net_qty: 50, greeks: { delta: -0.4, gamma: 0.02, theta: -4, vega: 8 } }),
    ]
    const group = makeGroup(legs)
    expect(group.net_gamma).toBeCloseTo(0.02 * 50 + 0.02 * 50)
  })

  it('aggregates theta across legs', () => {
    const legs = [
      makeLeg({ net_qty: 50, greeks: { delta: 0.4, gamma: 0.01, theta: -10, vega: 15 } }),
      makeLeg({ net_qty: -50, greeks: { delta: -0.4, gamma: 0.01, theta: -8, vega: 12 } }),
    ]
    const group = makeGroup(legs)
    // theta_net = -10 * 50 + (-8 * -50) = -500 + 400 = -100
    expect(group.net_theta).toBeCloseTo(-100)
  })

  it('sums total_pnl across all legs', () => {
    const legs = [
      makeLeg({ realized_pnl: 500, unrealized_pnl: -200 }),
      makeLeg({ realized_pnl: 300, unrealized_pnl: 100 }),
    ]
    const group = makeGroup(legs)
    expect(group.total_pnl).toBe(700)
  })

  it('handles legs with no greeks', () => {
    const legs = [
      makeLeg({ greeks: undefined }),
      makeLeg({ net_qty: 1, greeks: { delta: 1, gamma: 0, theta: 0, vega: 0 } }),
    ]
    const group = makeGroup(legs)
    // undefined greeks default to 0
    expect(group.net_delta).toBeCloseTo(1)
  })
})
