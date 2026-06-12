import { useState } from 'react'
import type { PositionalLeg, RolloverEstimate } from '../../types/positional'

interface Props {
  leg: PositionalLeg
}

function mid(bid: number, ask: number) {
  return (bid + ask) / 2
}

export function RolloverPanel({ leg }: Props) {
  const [slippagePct, setSlippagePct] = useState(0.1)
  const [estimate, setEstimate] = useState<RolloverEstimate | null>(null)
  const [noNextExpiry, setNoNextExpiry] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const underlying = leg.underlying ?? leg.security_id

  async function handleEstimate() {
    setLoading(true)
    setError(null)
    setNoNextExpiry(false)
    setEstimate(null)
    try {
      const resp = await fetch(`/api/v1/options/${underlying}/chain`)
      if (!resp.ok) throw new Error(`chain fetch failed: ${resp.status}`)
      const data = await resp.json()

      if (data.mode === 'paper' || !data.strikes?.length) {
        setError('No live chain data available (paper mode)')
        return
      }

      const expiries: string[] = [...new Set<string>(
        (data.strikes ?? []).flatMap((s: { call?: { expiry?: string }; put?: { expiry?: string } }) => [s.call?.expiry, s.put?.expiry].filter(Boolean))
      )].sort() as string[]

      if (!leg.expiry || expiries.length < 2) {
        setNoNextExpiry(true)
        return
      }

      const currentExpiry = leg.expiry
      const idx = expiries.indexOf(currentExpiry)
      const nextExpiry = expiries[idx + 1]
      if (!nextExpiry) {
        setNoNextExpiry(true)
        return
      }

      const strike = leg.strike
      const optType = leg.option_type

      const currentStrike = data.strikes.find((s: { strike: number }) => s.strike === strike)
      const nextData = await fetch(`/api/v1/options/${underlying}/chain?expiry=${nextExpiry}`)
      const nextChain = nextData.ok ? await nextData.json() : null
      const nextStrike = nextChain?.strikes?.find((s: { strike: number }) => s.strike === strike)

      const legKey = optType === 'CE' ? 'call' : 'put'
      const currLeg = currentStrike?.[legKey]
      const nextLeg = nextStrike?.[legKey]

      if (!currLeg || !nextLeg) {
        setError('Could not find matching strike in next expiry')
        return
      }

      const currentMid = mid(currLeg.bid_price ?? currLeg.ltp, currLeg.ask_price ?? currLeg.ltp)
      const nextMid = mid(nextLeg.bid_price ?? nextLeg.ltp, nextLeg.ask_price ?? nextLeg.ltp)
      const rolloverCost = nextMid - currentMid
      const slippageEst = (Math.abs(currentMid) + Math.abs(nextMid)) * (slippagePct / 100)

      setEstimate({
        underlying,
        strike: strike ?? 0,
        option_type: optType ?? 'CE',
        current_expiry: currentExpiry,
        next_expiry: nextExpiry,
        current_mid: currentMid,
        next_mid: nextMid,
        rollover_cost: rolloverCost,
        slippage_estimate: slippageEst,
      })
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const slippageEst = estimate
    ? (Math.abs(estimate.current_mid) + Math.abs(estimate.next_mid)) * (slippagePct / 100)
    : 0

  return (
    <div className="mt-2 p-3 bg-gray-900 border border-gray-700 rounded text-xs">
      <div className="flex items-center gap-3 mb-3">
        <span className="text-gray-400 font-medium">Rollover Estimator</span>
        <span className="text-gray-600">
          {leg.symbol ?? leg.security_id} {leg.expiry}
        </span>
        <button
          onClick={handleEstimate}
          disabled={loading}
          className="ml-auto px-3 py-1 bg-blue-800 hover:bg-blue-700 text-blue-100 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
          aria-busy={loading}
        >
          {loading ? 'Fetching…' : 'Estimate Rollover'}
        </button>
      </div>

      {noNextExpiry && (
        <p className="text-yellow-500">No next expiry available for rollover.</p>
      )}
      {error && <p className="text-red-400">{error}</p>}

      {estimate && (
        <div className="space-y-1">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className="text-gray-500">Current expiry mid</span>
              <span className="ml-2 font-mono text-white">₹{estimate.current_mid.toFixed(2)}</span>
              <span className="ml-1 text-gray-600">({estimate.current_expiry})</span>
            </div>
            <div>
              <span className="text-gray-500">Next expiry mid</span>
              <span className="ml-2 font-mono text-white">₹{estimate.next_mid.toFixed(2)}</span>
              <span className="ml-1 text-gray-600">({estimate.next_expiry})</span>
            </div>
            <div>
              <span className="text-gray-500">Rollover cost</span>
              <span className={`ml-2 font-mono font-semibold ${estimate.rollover_cost > 0 ? 'text-red-400' : 'text-green-400'}`}>
                ₹{estimate.rollover_cost.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor={`slippage-${leg.security_id}`} className="text-gray-500">Slippage buffer</label>
              <input
                id={`slippage-${leg.security_id}`}
                type="number"
                min="0"
                max="5"
                step="0.05"
                value={slippagePct}
                onChange={(e) => setSlippagePct(Number(e.target.value))}
                className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-white font-mono text-xs focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
              />
              <span className="text-gray-500">%</span>
              <span className="ml-2 font-mono text-yellow-300">₹{slippageEst.toFixed(2)}</span>
            </div>
          </div>
          <p className="text-gray-600 mt-2">Indicative only — mid-price estimate, actual fill will differ.</p>
        </div>
      )}
    </div>
  )
}
