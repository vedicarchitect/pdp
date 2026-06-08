import { useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { usePositionalFeeds } from '../../hooks/usePositionalFeeds'
import { useAllGreeks } from '../../hooks/useAllGreeks'
import { useEodHistory } from '../../hooks/useEodHistory'
import { StrategyGroupRow } from './StrategyGroupRow'
import { ExpiryAlertPanel } from './ExpiryAlertPanel'
import { PnLSparkline } from './PnLSparkline'
import type { FeedStatus, PositionalLeg, StrategyGroup } from '../../types/positional'

function StatusDot({ status }: { status: FeedStatus }) {
  const color =
    status === 'connected' ? 'bg-green-500' : status === 'connecting' ? 'bg-yellow-500' : 'bg-red-500'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}

export function PositionalPage() {
  const { groups, connectionState } = usePositionalFeeds()
  const { history, loading: histLoading } = useEodHistory(90)

  // Collect unique underlyings from legs that carry instrument metadata.
  // When a leg has `underlying` set (e.g., from a future instrument-registry enrichment step),
  // useAllGreeks will proactively fetch its option chain so Greeks are available even if the
  // /ws/portfolio message omits them (paper mode, non-option instruments).
  const underlyings = useMemo(() => {
    const set = new Set<string>()
    for (const g of groups) {
      for (const l of g.legs) {
        if (l.underlying) set.add(l.underlying)
      }
    }
    return [...set]
  }, [groups])

  const { lookupGreeks, isStale, lastFetchedAt } = useAllGreeks(underlyings)

  // Enrich legs: legs that have underlying+strike+option_type but lack WS Greeks
  // get them from the options chain. Legs with WS Greeks keep them unless the chain
  // is fresher (always prefer WS Greeks when available — they come from the live feed).
  const enrichedGroups: StrategyGroup[] = useMemo(() => {
    return groups.map((g) => ({
      ...g,
      legs: g.legs.map((leg): PositionalLeg => {
        if (leg.greeks != null) return leg   // WS already provided Greeks
        if (!leg.underlying || leg.strike == null || !leg.option_type) return leg  // no metadata
        const chainGreeks = lookupGreeks(leg.underlying, leg.strike, leg.option_type)
        if (!chainGreeks) return leg
        return {
          ...leg,
          greeks: { delta: chainGreeks.delta, gamma: chainGreeks.gamma, theta: chainGreeks.theta, vega: chainGreeks.vega, iv: chainGreeks.iv },
          greeks_stale: isStale(leg.underlying),
          greeks_updated_at: lastFetchedAt(leg.underlying) ?? undefined,
        }
      }),
    }))
  }, [groups, lookupGreeks, isStale, lastFetchedAt])

  const allLegs = enrichedGroups.flatMap((g) => g.legs)
  const hasPositions = allLegs.length > 0

  const totalPnl = enrichedGroups.reduce((s, g) => s + g.total_pnl, 0)
  const totalUnrealized = enrichedGroups.reduce((s, g) => s + g.unrealized_pnl, 0)
  const totalRealized = enrichedGroups.reduce((s, g) => s + g.realized_pnl, 0)

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Positional Monitor</h1>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <StatusDot status={connectionState} />
          <span>{connectionState}</span>
        </div>
      </div>

      {/* Expiry alerts */}
      <ExpiryAlertPanel legs={allLegs} />

      {/* P&L summary strip */}
      {hasPositions && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Day P&L', value: totalPnl },
            { label: 'Unrealized', value: totalUnrealized },
            { label: 'Realized', value: totalRealized },
          ].map(({ label, value }) => (
            <div key={label} className="bg-gray-900 border border-gray-800 rounded px-4 py-3">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className={`text-lg font-mono font-semibold ${value > 0 ? 'text-green-400' : value < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                ₹{value.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Strategy table */}
      {connectionState === 'connecting' && !hasPositions ? (
        <div className="text-gray-500 text-sm">Connecting to portfolio feed…</div>
      ) : !hasPositions ? (
        <div className="flex flex-col items-center gap-2 py-12 text-gray-500 text-sm">
          <span>No open positions</span>
          <Link to="/instruments" className="text-blue-400 hover:text-blue-300 underline text-xs">
            Browse instruments
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-700">
                <th className="px-3 py-2 text-left">Strategy / Leg</th>
                <th className="px-3 py-2 text-right">Δ Delta</th>
                <th className="px-3 py-2 text-right">Γ Gamma</th>
                <th className="px-3 py-2 text-right">Θ Theta</th>
                <th className="px-3 py-2 text-right">V Vega</th>
                <th className="px-3 py-2 text-right">Total P&L</th>
                <th className="px-3 py-2 text-right">Unrealized</th>
                <th className="px-3 py-2 text-right">Realized</th>
              </tr>
            </thead>
            <tbody>
              {enrichedGroups.map((group) => (
                <StrategyGroupRow key={group.strategy_id} group={group} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* EOD P&L history chart */}
      <div className="mt-2">
        <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wide">Daily P&L History</div>
        {histLoading ? (
          <div className="h-40 bg-gray-900 rounded border border-gray-800 flex items-center justify-center text-gray-600 text-sm">
            Loading…
          </div>
        ) : (
          <PnLSparkline history={history} />
        )}
      </div>
    </div>
  )
}
