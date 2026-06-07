import { useEffect, useRef, useState } from 'react'
import { usePortfolioWS } from './usePortfolioWS'
import type { FeedStatus, IntradayFeedState } from '../types/intraday'

export type { FeedStatus, IntradayFeedState }

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000
const STALE_WARN_MS = 5_000

interface OrdersState {
  status: FeedStatus
  lastUpdate: number | null
}

interface MarketState {
  status: FeedStatus
  lastUpdate: number | null
}

function useOrdersWS(): OrdersState {
  const [state, setState] = useState<OrdersState>({
    status: WS_DISABLED ? 'connected' : 'connecting',
    lastUpdate: null,
  })
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      setState((s) => ({ ...s, status: 'connecting' }))
      const ws = new WebSocket('/ws/orders')
      wsRef.current = ws

      ws.onopen = () => {
        if (mountedRef.current) setState((s) => ({ ...s, status: 'connected' }))
        backoffRef.current = 1_000
      }

      ws.onmessage = () => {
        if (mountedRef.current) setState({ status: 'connected', lastUpdate: Date.now() })
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

function useMarketFeedStatus(): MarketState {
  const [state, setState] = useState<MarketState>({
    status: WS_DISABLED ? 'connected' : 'connecting',
    lastUpdate: null,
  })
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      setState((s) => ({ ...s, status: 'connecting' }))
      const ws = new WebSocket('/ws/market')
      wsRef.current = ws

      ws.onopen = () => {
        if (mountedRef.current) setState((s) => ({ ...s, status: 'connected' }))
        backoffRef.current = 1_000
      }

      ws.onmessage = () => {
        if (mountedRef.current) setState({ status: 'connected', lastUpdate: Date.now() })
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

export function useIntradayFeeds(): IntradayFeedState {
  const portfolio = usePortfolioWS()
  const orders = useOrdersWS()
  const market = useMarketFeedStatus()

  // Log warning if any feed has been silent for >5s
  useEffect(() => {
    if (WS_DISABLED) return
    const interval = setInterval(() => {
      const now = Date.now()
      if (portfolio.status === 'connected' && orders.lastUpdate && now - orders.lastUpdate > STALE_WARN_MS) {
        console.warn('[intraday] orders feed silent for >5s')
      }
      if (portfolio.status === 'connected' && market.lastUpdate && now - market.lastUpdate > STALE_WARN_MS) {
        console.warn('[intraday] market feed silent for >5s')
      }
    }, STALE_WARN_MS)
    return () => clearInterval(interval)
  }, [portfolio.status, orders.lastUpdate, market.lastUpdate])

  const connected =
    portfolio.status === 'connected' &&
    orders.status === 'connected' &&
    market.status === 'connected'

  return {
    marketStatus: market.status,
    ordersStatus: orders.status,
    portfolioStatus: portfolio.status,
    positions: portfolio.positions,
    summary: portfolio.summary,
    connected,
  }
}
