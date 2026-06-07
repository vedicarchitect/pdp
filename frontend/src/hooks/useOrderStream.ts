import { useEffect, useRef, useState } from 'react'

export interface OrderUpdate {
  order_id: string
  status: string
  [key: string]: unknown
}

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000

export function useOrderStream(): OrderUpdate | null {
  const [update, setUpdate] = useState<OrderUpdate | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      const ws = new WebSocket('/ws/orders')
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data) as OrderUpdate
          if (mountedRef.current) {
            setUpdate(msg)
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

  return update
}
