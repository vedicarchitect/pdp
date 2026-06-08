import type { FeedStatus } from './intraday'

export type { FeedStatus }

export interface GreekValues {
  delta: number
  gamma: number
  theta: number
  vega: number
  iv?: number
}

export interface PositionalLeg {
  security_id: string
  exchange_segment: string
  product: string
  net_qty: number
  avg_price: number
  ltp?: number
  ltp_stale?: boolean
  realized_pnl: number
  unrealized_pnl: number
  updated_at: string
  strategy_id?: string
  // resolved from instrument registry / position tag
  symbol?: string
  expiry?: string   // YYYY-MM-DD
  underlying?: string
  option_type?: 'CE' | 'PE'
  strike?: number
  // enriched Greeks (from options snapshot)
  greeks?: GreekValues
  greeks_stale?: boolean
  greeks_updated_at?: string
}

export interface StrategyGroup {
  strategy_id: string
  legs: PositionalLeg[]
  net_delta: number
  net_gamma: number
  net_theta: number
  net_vega: number
  total_pnl: number
  unrealized_pnl: number
  realized_pnl: number
}

export interface DayPnL {
  date: string   // YYYY-MM-DD
  day_pnl: number
  total_unrealized_pnl: number
  total_realized_pnl: number
  position_count: number
  mode: string
  created_at: string
}

export interface RolloverEstimate {
  underlying: string
  strike: number
  option_type: 'CE' | 'PE'
  current_expiry: string
  next_expiry: string
  current_mid: number
  next_mid: number
  rollover_cost: number
  slippage_estimate: number
}

export interface PositionalFeedState {
  groups: StrategyGroup[]
  connectionState: FeedStatus
}
