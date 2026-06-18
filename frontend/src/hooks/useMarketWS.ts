import { useEffect, useRef, useState } from 'react'

export interface Tick {
  security_id: string
  ltp: number
  [key: string]: unknown
}

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000

export function useMarketWS(securityIds: string[]): Tick | null {
  const [tick, setTick] = useState<Tick | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED || securityIds.length === 0) return

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const params = securityIds.map((id) => `security_id=${encodeURIComponent(id)}`).join('&')
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/market?${params}`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as Tick
          if (mountedRef.current) {
            setTick(data)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [securityIds.join(',')])

  return tick
}
