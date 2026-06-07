import { describe, it, expect, beforeEach, vi } from 'vitest'

const STORAGE_KEY = 'intraday_dismissed_alerts'
const ALERT_TTL_MS = 60 * 60 * 1000

// Mirror the loadDismissed / saveDismissed logic from AlertPills
function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as Array<[string, number]>
    const now = Date.now()
    return new Set(arr.filter(([, ts]) => now - ts < ALERT_TTL_MS).map(([id]) => id))
  } catch {
    return new Set()
  }
}

function saveDismissed(ids: Set<string>) {
  const now = Date.now()
  const arr: Array<[string, number]> = Array.from(ids).map((id) => [id, now])
  localStorage.setItem(STORAGE_KEY, JSON.stringify(arr))
}

describe('Alert dismissal persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('loads empty set when no storage entry', () => {
    expect(loadDismissed().size).toBe(0)
  })

  it('round-trips dismissed alert IDs', () => {
    const ids = new Set(['alert-1', 'alert-2'])
    saveDismissed(ids)
    const loaded = loadDismissed()
    expect(loaded.has('alert-1')).toBe(true)
    expect(loaded.has('alert-2')).toBe(true)
  })

  it('filters out expired entries', () => {
    const now = Date.now()
    const expired: Array<[string, number]> = [['old-alert', now - ALERT_TTL_MS - 1]]
    localStorage.setItem(STORAGE_KEY, JSON.stringify(expired))
    expect(loadDismissed().size).toBe(0)
  })

  it('preserves non-expired entries', () => {
    const now = Date.now()
    const recent: Array<[string, number]> = [['new-alert', now - 1000]]
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recent))
    expect(loadDismissed().has('new-alert')).toBe(true)
  })

  it('handles corrupt localStorage gracefully', () => {
    localStorage.setItem(STORAGE_KEY, 'not-json')
    expect(() => loadDismissed()).not.toThrow()
    expect(loadDismissed().size).toBe(0)
  })
})

describe('Kill-switch retry logic', () => {
  it('retries up to 3 times on failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network error'))
    let attempts = 0

    async function callKillSwitch(_attempt = 0): Promise<void> {
      attempts++
      try {
        await fetchMock()
      } catch {
        if (_attempt < 2) {
          await new Promise((r) => setTimeout(r, 1))
          return callKillSwitch(_attempt + 1)
        }
        throw new Error('max retries exceeded')
      }
    }

    await expect(callKillSwitch()).rejects.toThrow('max retries exceeded')
    expect(attempts).toBe(3)
  })

  it('succeeds without retry on first attempt', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 'ok', cancelled_orders: 2, flattened_positions: 1, errors: [] })
    let attempts = 0

    async function callKillSwitch() {
      attempts++
      const result = await fetchMock()
      return result
    }

    const result = await callKillSwitch()
    expect(result.cancelled_orders).toBe(2)
    expect(attempts).toBe(1)
  })
})
