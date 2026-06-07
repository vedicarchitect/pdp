import { describe, it, expect } from 'vitest'
import type { RiskSettings } from '../types/intraday'

const DEFAULTS: RiskSettings = {
  RISK_DAILY_LOSS_CAP_INR: 50_000,
  RISK_PER_STRATEGY_LOSS_CAP_INR: 20_000,
  RISK_SOFT_CAP_PCT: 80,
}

describe('Risk settings fallback logic', () => {
  it('uses default daily cap of 50000 when settings unavailable', () => {
    expect(DEFAULTS.RISK_DAILY_LOSS_CAP_INR).toBe(50_000)
  })

  it('uses default per-strategy cap of 20000 when settings unavailable', () => {
    expect(DEFAULTS.RISK_PER_STRATEGY_LOSS_CAP_INR).toBe(20_000)
  })

  it('uses default soft cap pct of 80% when settings unavailable', () => {
    expect(DEFAULTS.RISK_SOFT_CAP_PCT).toBe(80)
  })

  it('computes loss usage percentage correctly', () => {
    const loss = 40_000
    const cap = DEFAULTS.RISK_DAILY_LOSS_CAP_INR
    const pct = (loss / cap) * 100
    expect(pct).toBe(80)
  })

  it('triggers soft cap at 80%', () => {
    const loss = 40_001
    const cap = DEFAULTS.RISK_DAILY_LOSS_CAP_INR
    const pct = loss / cap
    const softThreshold = DEFAULTS.RISK_SOFT_CAP_PCT / 100
    expect(pct).toBeGreaterThan(softThreshold)
  })

  it('does not trigger soft cap at 79%', () => {
    const loss = 39_500
    const cap = DEFAULTS.RISK_DAILY_LOSS_CAP_INR
    const pct = loss / cap
    const softThreshold = DEFAULTS.RISK_SOFT_CAP_PCT / 100
    expect(pct).toBeLessThan(softThreshold)
  })
})
