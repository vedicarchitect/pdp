import { useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { usePositionalFeeds } from '../../hooks/usePositionalFeeds'
import { useAllGreeks } from '../../hooks/useAllGreeks'
import { useEodHistory } from '../../hooks/useEodHistory'
import { StrategyGroupRow } from './StrategyGroupRow'
import { ExpiryAlertPanel } from './ExpiryAlertPanel'
import { PnLSparkline } from './PnLSparkline'
import { Card } from '@/components/ui/Card'
import type { FeedStatus, PositionalLeg, StrategyGroup } from '../../types/positional'

function StatusDot({ status }: { status: FeedStatus }) {
  const color =
    status === 'connected' ? 'bg-bullish' : status === 'connecting' ? 'bg-warning animate-pulse' : 'bg-bearish'
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
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <StatusDot status={connectionState} />
          <span>{connectionState}</span>
        </div>
      </div>

      {/* Expiry alerts */}
      <ExpiryAlertPanel legs={allLegs} />

      {/* P&L summary strip */}
      {hasPositions && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Day P&L', value: totalPnl },
            { label: 'Unrealized', value: totalUnrealized },
            { label: 'Realized', value: totalRealized },
          ].map(({ label, value }) => (
            <Card key={label} className="px-5 py-4 transition-transform duration-300 hover:-translate-y-1 hover:shadow-lg">
              <div className="text-xs font-medium text-text-muted mb-1.5 uppercase tracking-wider">{label}</div>
              <div className={`text-2xl font-mono font-bold ${value > 0 ? 'text-bullish' : value < 0 ? 'text-bearish' : 'text-text-muted'}`}>
                ₹{value.toFixed(2)}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Strategy table */}
      {connectionState === 'connecting' && !hasPositions ? (
        <div className="text-text-muted text-sm">Connecting to portfolio feed…</div>
      ) : !hasPositions ? (
        <div className="flex flex-col items-center gap-2 py-12 text-text-muted text-sm">
          <span>No open positions</span>
          <Link to="/instruments" className="text-primary hover:text-primary/80 underline text-xs transition-colors">
            Browse instruments
          </Link>
        </div>
      ) : (
        <Card className="overflow-x-auto rounded-xl">
          <table className="w-full text-sm">
            <thead className="bg-surface text-xs text-text-muted uppercase tracking-wider font-semibold border-b border-surface-border">
              <tr>
                <th className="px-4 py-3 text-left">Strategy / Leg</th>
                <th className="px-4 py-3 text-right">Δ Delta</th>
                <th className="px-4 py-3 text-right">Γ Gamma</th>
                <th className="px-4 py-3 text-right">Θ Theta</th>
                <th className="px-4 py-3 text-right">V Vega</th>
                <th className="px-4 py-3 text-right">Total P&L</th>
                <th className="px-4 py-3 text-right">Unrealized</th>
                <th className="px-4 py-3 text-right">Realized</th>
              </tr>
            </thead>
            <tbody>
              {enrichedGroups.map((group) => (
                <StrategyGroupRow key={group.strategy_id} group={group} />
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* EOD P&L history chart */}
      <div className="mt-4">
        <div className="text-xs font-medium text-text-muted mb-2 uppercase tracking-wide">Daily P&L History</div>
        {histLoading ? (
          <Card className="h-40 rounded-xl flex items-center justify-center text-text-muted text-sm font-medium">
            Loading…
          </Card>
        ) : (
          <PnLSparkline history={history} />
        )}
      </div>
    </div>
  )
}
