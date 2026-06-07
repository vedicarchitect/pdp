import { useEffect, useRef, useState } from 'react'

export interface PnLSummary {
  total_realized_pnl: number
  total_unrealized_pnl: number
  day_pnl: number
  realized_loss_today: number
  open_positions: number
}

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000

const STUB: PnLSummary = {
  total_realized_pnl: 0,
  total_unrealized_pnl: 0,
  day_pnl: 0,
  realized_loss_today: 0,
  open_positions: 0,
}

export function usePnL(): PnLSummary | null {
  const [summary, setSummary] = useState<PnLSummary | null>(WS_DISABLED ? STUB : null)
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      const ws = new WebSocket('/ws/portfolio')
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'portfolio_update' && msg.summary && mountedRef.current) {
            setSummary(msg.summary as PnLSummary)
            backoffRef.current = 1_000
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
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

  return summary
}
