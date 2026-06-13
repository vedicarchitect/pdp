import { createFileRoute } from '@tanstack/react-router'
import { useIntradayFeeds } from '../hooks/useIntradayFeeds'
import { useRiskSettings } from '../hooks/useRiskSettings'
import { PositionTable } from '../components/intraday/PositionTable'
import { RiskBanner } from '../components/intraday/RiskBanner'
import { AlertPills } from '../components/intraday/AlertPills'
import { KillSwitchButton } from '../components/intraday/KillSwitchButton'
import { ConnectionBadge } from '../components/intraday/ConnectionBadge'
import { FeedLoader } from '../components/intraday/FeedLoader'
import { RiskSettingsPanel } from '../components/intraday/RiskSettingsPanel'

export const Route = createFileRoute('/intraday')({
  component: IntradayPage,
})

function IntradayPage() {
  const feeds = useIntradayFeeds()
  const { settings, isDefault, isLoading } = useRiskSettings()

  return (
    <div className="flex flex-col gap-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Intraday Monitor</h1>
        <div className="flex items-center gap-4">
          <ConnectionBadge
            marketStatus={feeds.marketStatus}
            ordersStatus={feeds.ordersStatus}
            portfolioStatus={feeds.portfolioStatus}
          />
          <KillSwitchButton />
        </div>
      </div>

      {/* Risk settings row */}
      <RiskSettingsPanel
        settings={settings}
        isDefault={isDefault}
        isLoading={isLoading}
        dailyLoss={feeds.summary?.realized_loss_today ?? 0}
      />

      {/* Risk breach banner */}
      <RiskBanner summary={feeds.summary} settings={settings} />

      {/* Alerts */}
      <AlertPills
        positions={feeds.positions}
        summary={feeds.summary}
        settings={settings}
      />

      {/* P&L summary strip */}
      {feeds.summary && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Realized P&L', value: feeds.summary.total_realized_pnl },
            { label: 'Unrealized P&L', value: feeds.summary.total_unrealized_pnl },
            { label: 'Day P&L', value: feeds.summary.day_pnl },
            { label: 'Open Positions', value: feeds.summary.open_positions, isCount: true },
          ].map(({ label, value, isCount }) => (
            <div key={label} className="glass-panel rounded-xl px-5 py-4 transition-transform duration-300 hover:-translate-y-1 hover:shadow-lg">
              <div className="text-xs font-medium text-text-muted mb-1.5 uppercase tracking-wider">{label}</div>
              <div className={`text-2xl font-mono font-bold ${isCount ? 'text-text-main' : value > 0 ? 'text-bullish' : value < 0 ? 'text-bearish' : 'text-text-muted'}`}>
                {isCount ? value : `₹${value.toFixed(2)}`}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Position table with loading gate */}
      <FeedLoader
        marketStatus={feeds.marketStatus}
        ordersStatus={feeds.ordersStatus}
        portfolioStatus={feeds.portfolioStatus}
      >
        <PositionTable positions={feeds.positions} />
      </FeedLoader>
    </div>
  )
}
