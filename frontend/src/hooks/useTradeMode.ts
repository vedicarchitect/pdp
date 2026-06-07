import { useEffect, useState } from 'react'

export type TradeMode = 'paper' | 'live'

let _mode: TradeMode = 'paper'
const _listeners = new Set<(m: TradeMode) => void>()

export function setTradeMode(mode: TradeMode) {
  if (mode !== _mode) {
    _mode = mode
    _listeners.forEach((l) => l(mode))
  }
}

export function useTradeMode(): TradeMode {
  const [mode, setMode] = useState<TradeMode>(_mode)
  useEffect(() => {
    _listeners.add(setMode)
    return () => { _listeners.delete(setMode) }
  }, [])
  return mode
}

export function extractTradeModeFromResponse(response: Response) {
  const header = response.headers.get('x-trade-mode')
  if (header === 'live' || header === 'paper') {
    setTradeMode(header)
  }
}
