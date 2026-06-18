import { useState } from 'react'
import type { PositionalLeg } from '../../types/positional'
import { computeDTE } from '../../lib/utils'
import { RolloverPanel } from './RolloverPanel'

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function pnlClass(v: number) {
  return v > 0 ? 'text-bullish' : v < 0 ? 'text-bearish' : 'text-text-muted'
}

interface Props {
  leg: PositionalLeg
}

// Must match the 8 column header in PositionalPage: Strategy/Leg | Δ | Γ | Θ | V | Total P&L | Unrealized | Realized
const COL_SPAN = 8

export function LegRow({ leg }: Props) {
  const [showRollover, setShowRollover] = useState(false)

  const pnl = leg.realized_pnl + leg.unrealized_pnl
  const dte = leg.expiry ? computeDTE(leg.expiry) : null
  const hasGreeks = leg.greeks != null
  const isStale = leg.greeks_stale === true
  const hasExpiry = leg.expiry != null

  return (
    <>
      <tr className="border-t border-surface-border bg-background/50 text-xs">
        <td className="pl-10 py-2 text-text-muted font-mono">
          <div className="flex items-center gap-2">
            <div className="flex flex-col gap-0.5">
              <span className="text-text-main">{leg.symbol ?? leg.security_id}</span>
              <span className="text-text-subtle text-[11px]">
                {leg.net_qty > 0 ? '+' : ''}{leg.net_qty} @ ₹{fmt(leg.avg_price)}
                {leg.ltp != null && (
                  <span className="ml-1">
                    LTP ₹{fmt(leg.ltp)}
                    {leg.ltp_stale && <span className="ml-0.5 text-warning">⚠</span>}
                  </span>
                )}
                {leg.expiry && (
                  <span className="ml-1">
                    {leg.expiry}
                    {dte !== null && <span className="ml-0.5">(DTE {dte})</span>}
                  </span>
                )}
              </span>
            </div>
            {hasExpiry && (
              <button
                onClick={() => setShowRollover((v) => !v)}
                className={`ml-auto text-xs px-1.5 py-0.5 rounded border transition-colors ${
                  showRollover
                    ? 'border-primary/50 text-primary bg-primary/10'
                    : 'border-surface-border text-text-muted hover:border-surface-border-strong hover:text-text-main'
                }`}
                title="Toggle rollover cost estimator"
              >
                ⇄ Rollover
              </button>
            )}
          </div>
        </td>

        {/* Greeks — Δ Γ Θ V */}
        {hasGreeks ? (
          <>
            <td className="px-3 py-2 text-right font-mono text-text-muted">
              {fmt(leg.greeks!.delta, 3)}
              {isStale && (
                <span
                  className="ml-1 text-warning cursor-help"
                  title={leg.greeks_updated_at ? `Last updated: ${leg.greeks_updated_at}` : 'Greeks may be stale'}
                >
                  ⚠
                </span>
              )}
            </td>
            <td className="px-3 py-2 text-right font-mono text-text-muted">{fmt(leg.greeks!.gamma, 4)}</td>
            <td className="px-3 py-2 text-right font-mono text-text-muted">{fmt(leg.greeks!.theta, 2)}</td>
            <td className="px-3 py-2 text-right font-mono text-text-muted">{fmt(leg.greeks!.vega, 2)}</td>
          </>
        ) : (
          <>
            <td className="px-3 py-2 text-right text-text-subtle">—</td>
            <td className="px-3 py-2 text-right text-text-subtle">—</td>
            <td className="px-3 py-2 text-right text-text-subtle">—</td>
            <td className="px-3 py-2 text-right text-text-subtle">—</td>
          </>
        )}

        {/* P&L columns */}
        <td className={`px-3 py-2 text-right font-mono font-semibold ${pnlClass(pnl)}`}>₹{fmt(pnl)}</td>
        <td className={`px-3 py-2 text-right font-mono text-sm ${pnlClass(leg.unrealized_pnl)}`}>₹{fmt(leg.unrealized_pnl)}</td>
        <td className={`px-3 py-2 text-right font-mono text-sm ${pnlClass(leg.realized_pnl)}`}>₹{fmt(leg.realized_pnl)}</td>
      </tr>

      {/* Rollover panel — spans all columns */}
      {showRollover && (
        <tr className="bg-background/30">
          <td colSpan={COL_SPAN} className="px-4 pb-3">
            <RolloverPanel leg={leg} />
          </td>
        </tr>
      )}
    </>
  )
}
