import { useState } from 'react'
import type { PositionalLeg } from '../../types/positional'
import { computeDTE } from '../../lib/utils'
import { RolloverPanel } from './RolloverPanel'

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function pnlClass(v: number) {
  return v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-gray-400'
}

interface Props {
  leg: PositionalLeg
}

// Total column count in the positional table (must match PositionalPage header + LegRow cells).
const COL_SPAN = 9

export function LegRow({ leg }: Props) {
  const [showRollover, setShowRollover] = useState(false)

  const pnl = leg.realized_pnl + leg.unrealized_pnl
  const dte = leg.expiry ? computeDTE(leg.expiry) : null
  const hasGreeks = leg.greeks != null
  const isStale = leg.greeks_stale === true
  const hasExpiry = leg.expiry != null

  return (
    <>
      <tr className="border-t border-gray-800 bg-gray-950 text-xs">
        <td className="pl-10 py-2 text-gray-300 font-mono">
          <div className="flex items-center gap-2">
            <span>{leg.symbol ?? leg.security_id}</span>
            {leg.expiry && (
              <span className="text-gray-500">
                {leg.expiry}
                {dte !== null && <span className="ml-1 text-gray-600">(DTE {dte})</span>}
              </span>
            )}
            {hasExpiry && (
              <button
                onClick={() => setShowRollover((v) => !v)}
                className={`ml-auto text-xs px-1.5 py-0.5 rounded border transition-colors focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${
                  showRollover
                    ? 'border-blue-600 text-blue-400 bg-blue-950'
                    : 'border-gray-700 text-gray-500 hover:border-gray-500 hover:text-gray-300'
                }`}
                title="Toggle rollover cost estimator"
                aria-expanded={showRollover}
                aria-controls={`rollover-panel-${leg.security_id}`}
              >
                ⇄ Rollover
              </button>
            )}
          </div>
        </td>
        <td className="px-3 py-2 text-gray-400 text-right">{leg.net_qty}</td>
        <td className="px-3 py-2 text-gray-400 text-right font-mono">₹{fmt(leg.avg_price)}</td>
        <td className="px-3 py-2 text-gray-400 text-right font-mono">
          {leg.ltp != null ? `₹${fmt(leg.ltp)}` : <span className="text-gray-600">—</span>}
          {leg.ltp_stale && <span className="ml-1 text-yellow-600 text-xs">⚠</span>}
        </td>
        <td className={`px-3 py-2 text-right font-mono ${pnlClass(pnl)}`}>₹{fmt(pnl)}</td>

        {/* Greeks */}
        {hasGreeks ? (
          <>
            <td className="px-3 py-2 text-right font-mono text-gray-300">
              {fmt(leg.greeks!.delta, 3)}
              {isStale && (
                <span
                  className="ml-1 text-yellow-500 cursor-help"
                  title={leg.greeks_updated_at ? `Last updated: ${leg.greeks_updated_at}` : 'Greeks may be stale'}
                >
                  ⚠
                </span>
              )}
            </td>
            <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(leg.greeks!.gamma, 4)}</td>
            <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(leg.greeks!.theta, 2)}</td>
            <td className="px-3 py-2 text-right font-mono text-gray-300">{fmt(leg.greeks!.vega, 2)}</td>
          </>
        ) : (
          <>
            <td className="px-3 py-2 text-right text-gray-600">—</td>
            <td className="px-3 py-2 text-right text-gray-600">—</td>
            <td className="px-3 py-2 text-right text-gray-600">—</td>
            <td className="px-3 py-2 text-right text-gray-600">—</td>
          </>
        )}
      </tr>

      {/* Rollover panel — inline, spans all columns */}
      {showRollover && (
        <tr id={`rollover-panel-${leg.security_id}`} className="bg-gray-950">
          <td colSpan={COL_SPAN} className="px-4 pb-3">
            <RolloverPanel leg={leg} />
          </td>
        </tr>
      )}
    </>
  )
}
