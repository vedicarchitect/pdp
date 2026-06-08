import { useEffect, useState } from 'react'
import type { DayPnL } from '../types/positional'

export interface EodHistoryState {
  history: DayPnL[]
  loading: boolean
  error: string | null
}

export function useEodHistory(days = 90): EodHistoryState {
  const [state, setState] = useState<EodHistoryState>({ history: [], loading: true, error: null })

  useEffect(() => {
    async function fetch_() {
      try {
        const resp = await fetch(`/api/v1/positional/snapshots?days=${days}`)
        if (!resp.ok) throw new Error(`snapshots fetch failed: ${resp.status}`)
        const data: DayPnL[] = await resp.json()
        const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date))
        setState({ history: sorted, loading: false, error: null })
      } catch (e) {
        setState({ history: [], loading: false, error: String(e) })
      }
    }
    fetch_()
  }, [days])

  return state
}
