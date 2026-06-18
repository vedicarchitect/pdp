export interface PayoffLeg {
  id: string // Client-side ID for list rendering
  strike: number
  expiry: string
  option_type: 'CE' | 'PE'
  side: 'BUY' | 'SELL'
  lots: number
  premium: number
  iv: number
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
}

export interface PayoffResult {
  pnl_curve: { spot: number; pnl: number }[]
  breakevens: number[]
  max_profit: number | null
  max_loss: number | null
  net_greeks: { delta: number; gamma: number; theta: number; vega: number }
  probability_of_profit: number
  margin_estimate: number | null
  margin_is_approximate: boolean
}

export interface ReadymadeStrategy {
  name: string
  legs: {
    offset: number
    type: 'CE' | 'PE'
    side: 'BUY' | 'SELL'
    lots: number
  }[]
}
