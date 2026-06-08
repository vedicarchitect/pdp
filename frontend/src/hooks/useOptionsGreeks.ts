import { useEffect, useState } from 'react'
import type { GreekValues } from '../types/positional'

const STALE_MS = 60_000

export interface StrikeGreeks extends GreekValues {
  strike: number
  option_type: 'CE' | 'PE'
}

export interface OptionsGreeksState {
  // keyed by `${strike}_${option_type}`
  greeks: Record<string, StrikeGreeks>
  lastUpdated: number | null
  isStale: boolean
  error: string | null
}

export function useOptionsGreeks(underlying: string | undefined): OptionsGreeksState {
  const [state, setState] = useState<OptionsGreeksState>({
    greeks: {},
    lastUpdated: null,
    isStale: false,
    error: null,
  })

  useEffect(() => {
    if (!underlying) return

    async function fetchChain() {
      try {
        const resp = await fetch(`/api/v1/options/${underlying}/chain`)
        if (!resp.ok) throw new Error(`chain fetch failed: ${resp.status}`)
        const data = await resp.json()
        if (data.mode === 'paper' || !data.strikes?.length) {
          setState({ greeks: {}, lastUpdated: Date.now(), isStale: false, error: null })
          return
        }
        const map: Record<string, StrikeGreeks> = {}
        for (const s of data.strikes) {
          for (const side of ['CE', 'PE'] as const) {
            const leg = side === 'CE' ? s.call : s.put
            if (!leg) continue
            const key = `${s.strike}_${side}`
            map[key] = {
              strike: s.strike,
              option_type: side,
              delta: leg.delta ?? 0,
              gamma: leg.gamma ?? 0,
              theta: leg.theta ?? 0,
              vega: leg.vega ?? 0,
              iv: leg.iv ?? undefined,
            }
          }
        }
        const now = Date.now()
        setState({ greeks: map, lastUpdated: now, isStale: false, error: null })
      } catch (e) {
        setState((s) => ({ ...s, error: String(e) }))
      }
    }

    fetchChain()
  }, [underlying])

  // Staleness check
  useEffect(() => {
    const id = setInterval(() => {
      setState((s) => ({
        ...s,
        isStale: s.lastUpdated != null && Date.now() - s.lastUpdated > STALE_MS,
      }))
    }, 5_000)
    return () => clearInterval(id)
  }, [])

  return state
}
