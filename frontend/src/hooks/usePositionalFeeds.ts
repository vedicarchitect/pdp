import { useEffect, useRef, useState } from 'react'
import type { FeedStatus, PositionalFeedState, PositionalLeg, StrategyGroup } from '../types/positional'
import type { Position } from '../types/intraday'

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'
const MAX_BACKOFF_MS = 30_000

function groupPositions(positions: Position[]): StrategyGroup[] {
  const map = new Map<string, PositionalLeg[]>()

  for (const p of positions) {
    const key = p.strategy_id ?? 'Untagged'
    const leg: PositionalLeg = {
      security_id: p.security_id,
      exchange_segment: p.exchange_segment,
      product: p.product,
      net_qty: p.net_qty,
      avg_price: Number(p.avg_price),
      ltp: p.ltp,
      ltp_stale: p.ltp_stale,
      realized_pnl: Number(p.realized_pnl),
      unrealized_pnl: Number(p.unrealized_pnl),
      updated_at: p.updated_at,
      strategy_id: p.strategy_id,
      greeks: p.delta != null ? { delta: p.delta ?? 0, gamma: p.gamma ?? 0, theta: p.theta ?? 0, vega: p.vega ?? 0 } : undefined,
    }
    const existing = map.get(key) ?? []
    existing.push(leg)
    map.set(key, existing)
  }

  const groups: StrategyGroup[] = []
  for (const [strategy_id, legs] of map.entries()) {
    const net_delta = legs.reduce((s, l) => s + (l.greeks?.delta ?? 0) * l.net_qty, 0)
    const net_gamma = legs.reduce((s, l) => s + (l.greeks?.gamma ?? 0) * l.net_qty, 0)
    const net_theta = legs.reduce((s, l) => s + (l.greeks?.theta ?? 0) * l.net_qty, 0)
    const net_vega = legs.reduce((s, l) => s + (l.greeks?.vega ?? 0) * l.net_qty, 0)
    const unrealized_pnl = legs.reduce((s, l) => s + l.unrealized_pnl, 0)
    const realized_pnl = legs.reduce((s, l) => s + l.realized_pnl, 0)
    groups.push({
      strategy_id,
      legs,
      net_delta,
      net_gamma,
      net_theta,
      net_vega,
      unrealized_pnl,
      realized_pnl,
      total_pnl: unrealized_pnl + realized_pnl,
    })
  }

  // Sort: named strategies first, Untagged last
  return groups.sort((a, b) => {
    if (a.strategy_id === 'Untagged') return 1
    if (b.strategy_id === 'Untagged') return -1
    return a.strategy_id.localeCompare(b.strategy_id)
  })
}

const STUB: PositionalFeedState = {
  groups: [],
  connectionState: 'connected',
}

export function usePositionalFeeds(): PositionalFeedState {
  const [state, setState] = useState<PositionalFeedState>(
    WS_DISABLED ? STUB : { groups: [], connectionState: 'connecting' }
  )
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1_000)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    if (WS_DISABLED) return

    function connect() {
      if (mountedRef.current) setState((s) => ({ ...s, connectionState: 'connecting' }))
      const ws = new WebSocket('/ws/portfolio')
      wsRef.current = ws

      ws.onopen = () => {
        if (mountedRef.current) setState((s) => ({ ...s, connectionState: 'connected' }))
        backoffRef.current = 1_000
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'portfolio_update' && mountedRef.current) {
            setState({ groups: groupPositions(msg.positions ?? []), connectionState: 'connected' })
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setState((s) => ({ ...s, connectionState: 'disconnected' }))
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
