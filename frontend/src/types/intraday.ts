export interface Position {
  security_id: string
  exchange_segment: string
  product: string
  net_qty: number
  avg_price: number
  realized_pnl: number
  unrealized_pnl: number
  ltp?: number
  ltp_stale?: boolean
  updated_at: string
  strategy_id?: string
  // Option Greeks (present when instrument is an option)
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
}

export interface StrategyGroup {
  strategy_id: string
  positions: Position[]
  total_delta: number
  total_gamma: number
  total_theta: number
  total_vega: number
  total_pnl: number
  realized_pnl: number
  unrealized_pnl: number
}

export interface PnLSummary {
  total_realized_pnl: number
  total_unrealized_pnl: number
  day_pnl: number
  realized_loss_today: number
  open_positions: number
}

export interface PortfolioUpdate {
  type: 'portfolio_update'
  positions: Position[]
  summary?: PnLSummary
}

export interface RiskSettings {
  RISK_DAILY_LOSS_CAP_INR: number
  RISK_PER_STRATEGY_LOSS_CAP_INR: number
  RISK_SOFT_CAP_PCT: number
}

export type AlertType = 'price' | 'pnl' | 'time'

export interface Alert {
  id: string
  type: AlertType
  message: string
  timestamp: number
  strategy_id?: string
  security_id?: string
}

export type FeedStatus = 'connecting' | 'connected' | 'disconnected'

export interface IntradayFeedState {
  marketStatus: FeedStatus
  ordersStatus: FeedStatus
  portfolioStatus: FeedStatus
  positions: Position[]
  summary: PnLSummary | null
  connected: boolean
}
