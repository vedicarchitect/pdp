import { describe, it, expect } from 'vitest'
import { computeDTE } from '../lib/utils'

function makeDateStr(daysFromNow: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + daysFromNow)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

describe('computeDTE', () => {
  it('returns 0 for same-day expiry', () => {
    expect(computeDTE(makeDateStr(0))).toBe(0)
  })

  it('returns 1 for tomorrow', () => {
    expect(computeDTE(makeDateStr(1))).toBe(1)
  })

  it('returns 7 for 7 days out', () => {
    expect(computeDTE(makeDateStr(7))).toBe(7)
  })

  it('returns 8 for 8 days out', () => {
    expect(computeDTE(makeDateStr(8))).toBe(8)
  })

  it('returns 0 for past dates (floor to 0)', () => {
    expect(computeDTE(makeDateStr(-5))).toBe(0)
  })
})

describe('Expiry alert severity logic', () => {
  function severity(dte: number): string {
    if (dte <= 1) return 'CRITICAL'
    if (dte <= 3) return 'URGENT'
    if (dte <= 7) return 'WARNING'
    return 'NONE'
  }

  it('DTE=0 → CRITICAL', () => expect(severity(0)).toBe('CRITICAL'))
  it('DTE=1 → CRITICAL', () => expect(severity(1)).toBe('CRITICAL'))
  it('DTE=2 → URGENT', () => expect(severity(2)).toBe('URGENT'))
  it('DTE=3 → URGENT', () => expect(severity(3)).toBe('URGENT'))
  it('DTE=4 → WARNING', () => expect(severity(4)).toBe('WARNING'))
  it('DTE=7 → WARNING', () => expect(severity(7)).toBe('WARNING'))
  it('DTE=8 → NONE (no alert)', () => expect(severity(8)).toBe('NONE'))
})
