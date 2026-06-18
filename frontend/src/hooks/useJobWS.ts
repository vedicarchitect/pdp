import { useEffect, useRef, useState, useCallback } from 'react'

export type JobProgressEvent = {
  progress: number
  message: string
}

export type UseJobWSResult = {
  progress: number
  message: string
  done: boolean
}

export function useJobWS(jobId: string | null): UseJobWSResult {
  const [state, setState] = useState<UseJobWSResult>({ progress: 0, message: '', done: false })
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!jobId || !mountedRef.current) return

    const url = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/jobs/${jobId}`
    const ws = new WebSocket(url.replace(window.location.host, 'localhost:8000'))
    wsRef.current = ws

    ws.onmessage = (ev) => {
      try {
        const payload: JobProgressEvent = JSON.parse(ev.data)
        const isDone =
          payload.message === 'Completed' ||
          payload.message === 'Cancelled' ||
          payload.message.startsWith('Failed:')

        if (mountedRef.current) {
          setState({ progress: payload.progress, message: payload.message, done: isDone })
        }
        if (isDone) ws.close()
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => ws.close()

    ws.onclose = () => {
      if (!mountedRef.current) return
      // Auto-reconnect if job is not yet done (server closed before terminal message)
      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current && wsRef.current?.readyState !== WebSocket.OPEN) {
          connect()
        }
      }, 2000)
    }
  }, [jobId])

  useEffect(() => {
    mountedRef.current = true
    setState({ progress: 0, message: '', done: false })

    if (jobId) connect()

    return () => {
      mountedRef.current = false
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [jobId, connect])

  return state
}
