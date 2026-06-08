import { describe, it, expect } from 'vitest'

function computeRolloverCost(currentMid: number, nextMid: number) {
  return nextMid - currentMid
}

function computeSlippage(currentMid: number, nextMid: number, slippagePct: number) {
  return (Math.abs(currentMid) + Math.abs(nextMid)) * (slippagePct / 100)
}

function mid(bid: number, ask: number) {
  return (bid + ask) / 2
}

describe('Rollover cost calculation', () => {
  it('computes positive rollover cost when next > current', () => {
    const cost = computeRolloverCost(100, 120)
    expect(cost).toBeCloseTo(20)
  })

  it('computes negative rollover cost when next < current (credit roll)', () => {
    const cost = computeRolloverCost(120, 100)
    expect(cost).toBeCloseTo(-20)
  })

  it('computes zero cost when same mid price', () => {
    expect(computeRolloverCost(100, 100)).toBe(0)
  })

  it('computes mid correctly from bid/ask', () => {
    expect(mid(95, 105)).toBe(100)
    expect(mid(18, 22)).toBe(20)
  })
})

describe('Slippage estimate', () => {
  it('computes slippage at default 0.1% of combined mids', () => {
    const slip = computeSlippage(100, 120, 0.1)
    expect(slip).toBeCloseTo(0.22) // (100 + 120) * 0.001
  })

  it('slippage scales with pct input', () => {
    const slip05 = computeSlippage(100, 100, 0.5)
    const slip01 = computeSlippage(100, 100, 0.1)
    expect(slip05).toBeCloseTo(slip01 * 5)
  })

  it('slippage is always non-negative even for negative mids', () => {
    const slip = computeSlippage(-50, -60, 0.1)
    expect(slip).toBeGreaterThan(0)
  })

  it('zero slippage at 0% input', () => {
    expect(computeSlippage(100, 100, 0)).toBe(0)
  })
})
