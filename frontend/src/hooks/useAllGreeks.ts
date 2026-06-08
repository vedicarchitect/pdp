import { useEffect, useState } from 'react'
import type { GreekValues } from '../types/positional'

const STALE_MS = 60_000

export interface StrikeGreeks extends GreekValues {
  strike: number
  option_type: 'CE' | 'PE'
}

interface UnderlyingEntry {
  greeks: Record<string, StrikeGreeks>  // key: `${strike}_${optionType}`
  fetchedAt: number
}

interface AllGreeksState {
  /** Look up per-strike Greeks for a given underlying. Returns undefined when no snapshot exists. */
  lookupGreeks: (underlying: string, strike: number, optionType: 'CE' | 'PE') => StrikeGreeks | undefined
  /** Whether the snapshot for an underlying is older than 60 s. */
  isStale: (underlying: string) => boolean
  /** ISO timestamp when the underlying's snapshot was last fetched (for tooltip). */
  lastFetchedAt: (underlying: string) => string | null
}

/**
 * Fetches and caches option-chain Greeks for an array of underlyings.
 * Re-fetches whenever the sorted underlyings list changes.
 * Falls back gracefully (returns undefined) when chain is unavailable (paper mode, no poller).
 */
export function useAllGreeks(underlyings: string[]): AllGreeksState {
  const [map, setMap] = useState<Record<string, UnderlyingEntry>>({})

  // Stable key so useEffect only fires when the underlying list actually changes
  const key = [...underlyings].sort().join(',')

  useEffect(() => {
    if (!underlyings.length) return

    Promise.all(
      underlyings.map(async (u): Promise<[string, UnderlyingEntry | null]> => {
        try {
          const resp = await fetch(`/api/v1/options/${u}/chain`)
          if (!resp.ok) return [u, null]
          const data = await resp.json()
          if (data.mode === 'paper' || !data.strikes?.length) return [u, null]

          const greeks: Record<string, StrikeGreeks> = {}
          for (const s of data.strikes as Array<{ strike: number; call?: Record<string, number>; put?: Record<string, number> }>) {
            for (const side of ['CE', 'PE'] as const) {
              const leg = side === 'CE' ? s.call : s.put
              if (!leg) continue
              greeks[`${s.strike}_${side}`] = {
                strike: s.strike,
                option_type: side,
                delta: leg.delta ?? 0,
                gamma: leg.gamma ?? 0,
                theta: leg.theta ?? 0,
                vega: leg.vega ?? 0,
                iv: leg.implied_volatility ?? undefined,
              }
            }
          }
          return [u, { greeks, fetchedAt: Date.now() }]
        } catch {
          return [u, null]
        }
      })
    ).then((entries) => {
      setMap((prev) => {
        const next = { ...prev }
        for (const [u, entry] of entries) {
          if (entry) next[u] = entry
        }
        return next
      })
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  function lookupGreeks(underlying: string, strike: number, optionType: 'CE' | 'PE') {
    return map[underlying]?.greeks[`${strike}_${optionType}`]
  }

  function isStale(underlying: string) {
    const entry = map[underlying]
    return entry != null && Date.now() - entry.fetchedAt > STALE_MS
  }

  function lastFetchedAt(underlying: string) {
    const ts = map[underlying]?.fetchedAt
    return ts ? new Date(ts).toISOString() : null
  }

  return { lookupGreeks, isStale, lastFetchedAt }
}
