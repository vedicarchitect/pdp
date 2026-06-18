import { useEffect, useRef, useState } from 'react'
import type { FeedStatus, PnLSummary, Position } from '../types/intraday'

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000

interface PortfolioState {
  positions: Position[]
  summary: PnLSummary | null
  status: FeedStatus
}

const STUB: PortfolioState = {
  positions: [],
  summary: { total_realized_pnl: 0, total_unrealized_pnl: 0, day_pnl: 0, realized_loss_today: 0, open_positions: 0 },
  status: 'connected',
}

export function usePortfolioWS(): PortfolioState {
  const [state, setState] = useState<PortfolioState>(
    WS_DISABLED ? STUB : { positions: [], summary: null, status: 'connecting' }
  )
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      if (mountedRef.current) setState((s) => ({ ...s, status: 'connecting' }))
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/portfolio`)
      wsRef.current = ws

      ws.onopen = () => {
        if (mountedRef.current) setState((s) => ({ ...s, status: 'connected' }))
        backoffRef.current = 1_000
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'portfolio_update' && mountedRef.current) {
            setState({ positions: msg.positions ?? [], summary: msg.summary ?? null, status: 'connected' })
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setState((s) => ({ ...s, status: 'disconnected' }))
        const delay = backoffRef.current
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS)
        retryRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      mountedRef.current = false
      if (retryRef.current) clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [])

  return state
}
