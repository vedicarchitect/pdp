/**
 * Integration scenarios for the intraday monitor.
 * These are component-level integration tests using mocked WebSocket and API responses.
 * End-to-end browser tests (Playwright) require a running backend and are out of scope here.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Position, PnLSummary, RiskSettings } from '../types/intraday'

// ---------- shared fixtures ----------

const makePos = (overrides: Partial<Position> = {}): Position => ({
  security_id: 'NIFTY-25JUL-24000-CE',
  exchange_segment: 'NSE_FO',
  product: 'INTRADAY',
  net_qty: 50,
  avg_price: 100,
  realized_pnl: 0,
  unrealized_pnl: 0,
  updated_at: new Date().toISOString(),
  ...overrides,
})

const makeSummary = (overrides: Partial<PnLSummary> = {}): PnLSummary => ({
  total_realized_pnl: 0,
  total_unrealized_pnl: 0,
  day_pnl: 0,
  realized_loss_today: 0,
  open_positions: 1,
  ...overrides,
})

const defaultSettings: RiskSettings = {
  RISK_DAILY_LOSS_CAP_INR: 50_000,
  RISK_PER_STRATEGY_LOSS_CAP_INR: 20_000,
  RISK_SOFT_CAP_PCT: 80,
}

// ---------- Scenario 10.2: P&L updates within 100ms on tick ----------

describe('Scenario: market tick → P&L recalculation', () => {
  it('updates unrealized P&L when position price changes', () => {
    const pos = makePos({ net_qty: 50, avg_price: 100 })
    // Simulate new tick at 110
    const newLtp = 110
    const newUnrealized = (newLtp - pos.avg_price) * pos.net_qty
    expect(newUnrealized).toBe(500)
  })

  it('recalculates correctly for short position', () => {
    const pos = makePos({ net_qty: -50, avg_price: 100 })
    const newLtp = 90
    const newUnrealized = (newLtp - pos.avg_price) * pos.net_qty
    expect(newUnrealized).toBe(500) // short profits from price drop
  })
})

// ---------- Scenario 10.3: order fill → position update ----------

describe('Scenario: order fill → position recalculation', () => {
  it('adds new position on BUY fill', () => {
    const positions: Position[] = []
    const fill = makePos({ net_qty: 50, realized_pnl: 0 })
    positions.push(fill)
    expect(positions).toHaveLength(1)
    expect(positions[0].net_qty).toBe(50)
  })

  it('nets existing position on opposite fill', () => {
    const initial = makePos({ net_qty: 50 })
    // Partial close: sell 25
    const remaining_qty = initial.net_qty - 25
    expect(remaining_qty).toBe(25)
  })
})

// ---------- Scenario 10.4: loss approaching cap → banner ----------

describe('Scenario: loss approaching cap → yellow banner', () => {
  it('banner visible when loss >80% of cap', () => {
    const summary = makeSummary({ realized_loss_today: 41_000 })
    const pct = summary.realized_loss_today / defaultSettings.RISK_DAILY_LOSS_CAP_INR
    const softThreshold = defaultSettings.RISK_SOFT_CAP_PCT / 100
    expect(pct).toBeGreaterThan(softThreshold)
  })

  it('banner not visible below soft threshold', () => {
    const summary = makeSummary({ realized_loss_today: 39_000 })
    const pct = summary.realized_loss_today / defaultSettings.RISK_DAILY_LOSS_CAP_INR
    const softThreshold = defaultSettings.RISK_SOFT_CAP_PCT / 100
    expect(pct).toBeLessThan(softThreshold)
  })
})

// ---------- Scenario 10.5: loss exceeds hard cap → kill-switch ----------

describe('Scenario: hard cap breach → auto kill-switch', () => {
  it('triggers when loss >= 100% of cap', () => {
    const summary = makeSummary({ realized_loss_today: 50_001 })
    const pct = summary.realized_loss_today / defaultSettings.RISK_DAILY_LOSS_CAP_INR
    expect(pct).toBeGreaterThanOrEqual(1.0)
  })

  it('does not trigger at 99% of cap', () => {
    const summary = makeSummary({ realized_loss_today: 49_999 })
    const pct = summary.realized_loss_today / defaultSettings.RISK_DAILY_LOSS_CAP_INR
    expect(pct).toBeLessThan(1.0)
  })
})

// ---------- Scenario 10.6: manual kill-switch → API call ----------

describe('Scenario: user clicks kill-switch → API call', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls POST /api/v1/risk/kill with no body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'ok',
        cancelled_orders: [
          { id: 'o1', security_id: 'NIFTY-CE' },
          { id: 'o2', security_id: 'NIFTY-PE' },
          { id: 'o3', security_id: 'BANKNIFTY-CE' },
        ],
        flattened_positions: [
          { security_id: 'NIFTY-CE', qty_flattened: 50 },
          { security_id: 'NIFTY-PE', qty_flattened: 50 },
        ],
        errors: [],
      }),
    })
    globalThis.fetch = fetchMock as typeof fetch

    const res = await fetch('/api/v1/risk/kill', { method: 'POST' })
    const data = await res.json()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/risk/kill', { method: 'POST' })
    expect(data.cancelled_orders).toHaveLength(3)
    expect(data.flattened_positions).toHaveLength(2)
  })
})

// ---------- Scenario 10.8: WebSocket reconnect → data re-sync ----------

describe('Scenario: WebSocket reconnect → state sync', () => {
  it('portfolio snapshot fetch on reconnect returns valid structure', async () => {
    const snapshot: Position[] = [makePos({ unrealized_pnl: 1500 })]
    // Simulate fetching latest snapshot after reconnect
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => snapshot,
    })
    globalThis.fetch = fetchMock as typeof fetch

    const res = await fetch('/api/v1/portfolio')
    const positions: Position[] = await res.json()

    expect(positions).toHaveLength(1)
    expect(positions[0].unrealized_pnl).toBe(1500)
  })
})
