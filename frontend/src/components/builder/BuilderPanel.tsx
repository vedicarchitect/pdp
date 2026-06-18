import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Select } from '@/components/ui/Select'
import { ReadymadeSelector } from './ReadymadeSelector'
import { LegTable } from './LegTable'
import { ChainPicker } from './ChainPicker'
import { PayoffChart } from './PayoffChart'
import { GreeksPanel } from './GreeksPanel'
import { OrderEntry, type OrderPrefill } from '@/components/orders/OrderEntry'
import type { PayoffLeg, ReadymadeStrategy, PayoffResult } from '../../types/builder'

export function BuilderPanel() {
  const [underlying, setUnderlying] = useState('NIFTY')
  const [legs, setLegs] = useState<PayoffLeg[]>([])
  const [lotSize, setLotSize] = useState(75)
  const [orderPrefill, setOrderPrefill] = useState<OrderPrefill | null>(null)

  // Fetch latest spot from chain to feed the payoff engine
  const { data: chainData } = useQuery({
    queryKey: ['chain', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/chain`)
      if (!res.ok) throw new Error('Failed to fetch chain')
      return res.json()
    },
    refetchInterval: 10000,
  })

  const spot = chainData?.spot_price || 0
  const strikes = chainData?.strikes || []
  const expiry = chainData?.expiry || ''

  // Debounced payload to prevent spamming the backend while typing
  const [debouncedLegs, setDebouncedLegs] = useState<PayoffLeg[]>([])
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedLegs(legs)
    }, 500)
    return () => clearTimeout(timer)
  }, [legs])

  const { data: payoffResult, isLoading: isPayoffLoading } = useQuery<PayoffResult>({
    queryKey: ['payoff', underlying, spot, debouncedLegs],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/payoff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          legs: debouncedLegs.map(l => ({
            strike: l.strike,
            expiry: l.expiry || expiry,
            option_type: l.option_type,
            side: l.side,
            lots: l.lots,
            premium: l.premium,
            iv: l.iv,
            delta: l.delta || 0,
            gamma: l.gamma || 0,
            theta: l.theta || 0,
            vega: l.vega || 0,
          })),
          spot: spot,
          lot_size: lotSize,
          days_to_expiry: 7, // Approximate, ideally compute from expiry date
        }),
      })
      if (!res.ok) throw new Error('Failed to fetch payoff')
      return res.json()
    },
    enabled: debouncedLegs.length > 0 && spot > 0,
  })

  const handleApplyReadymade = (strategy: ReadymadeStrategy) => {
    if (!spot || strikes.length === 0) return

    const atmIdx = strikes.findIndex((s: any) => s.strike >= spot)
    if (atmIdx === -1) return

    const newLegs: PayoffLeg[] = strategy.legs.map((legDef) => {
      const targetIdx = Math.max(0, Math.min(strikes.length - 1, atmIdx + legDef.offset))
      const targetStrike = strikes[targetIdx]
      
      const optData = legDef.type === 'CE' ? targetStrike.ce : targetStrike.pe
      return {
        id: crypto.randomUUID(),
        strike: targetStrike.strike,
        expiry: expiry,
        option_type: legDef.type,
        side: legDef.side,
        lots: legDef.lots,
        premium: optData?.last_price || 0,
        iv: optData?.iv || 0.2,
        delta: optData?.delta || 0,
        gamma: optData?.gamma || 0,
        theta: optData?.theta || 0,
        vega: optData?.vega || 0,
      }
    })
    setLegs(newLegs)
  }

  const handleUnderlyingChange = (val: string) => {
    setUnderlying(val)
    setLegs([])
    setLotSize(val === 'NIFTY' ? 75 : val === 'BANKNIFTY' ? 15 : 10)
  }

  const handleTradeLeg = (leg: PayoffLeg) => {
    setOrderPrefill({
      security_id: `${underlying}_${leg.strike}_${leg.option_type}`,
      exchange_segment: "NSE_FO",
      side: leg.side as "BUY" | "SELL",
      qty: leg.lots * lotSize,
      order_type: "LIMIT",
      price: leg.premium,
      product: "INTRADAY",
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <Select 
          value={underlying} 
          onChange={(e) => handleUnderlyingChange(e.target.value)}
          className="w-48"
        >
          <option value="NIFTY">NIFTY</option>
          <option value="BANKNIFTY">BANKNIFTY</option>
          <option value="SENSEX">SENSEX</option>
        </Select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Builder Controls */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          <ReadymadeSelector 
            underlying={underlying} 
            onSelect={handleApplyReadymade} 
          />
          <LegTable
            legs={legs}
            onChange={setLegs}
            onTrade={handleTradeLeg}
          />
          <ChainPicker 
            underlying={underlying} 
            onAddLeg={(leg) => setLegs([...legs, { ...leg, id: crypto.randomUUID() }])} 
          />
        </div>

        {/* Right Column: Analytics */}
        <div className="flex flex-col gap-6">
          <PayoffChart 
            data={payoffResult?.pnl_curve} 
            breakevens={payoffResult?.breakevens || []}
            spot={spot}
          />
          <div className="flex-1 min-h-[300px]">
            <GreeksPanel 
              result={payoffResult || null} 
              isLoading={isPayoffLoading} 
            />
          </div>
        </div>
      </div>
      {orderPrefill && (
        <OrderEntry
          open={!!orderPrefill}
          onOpenChange={(open) => !open && setOrderPrefill(null)}
          prefill={orderPrefill}
        />
      )}
    </div>
  )
}
