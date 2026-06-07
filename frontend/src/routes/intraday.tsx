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
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Realized P&L', value: feeds.summary.total_realized_pnl },
            { label: 'Unrealized P&L', value: feeds.summary.total_unrealized_pnl },
            { label: 'Day P&L', value: feeds.summary.day_pnl },
            { label: 'Open Positions', value: feeds.summary.open_positions, isCount: true },
          ].map(({ label, value, isCount }) => (
            <div key={label} className="bg-gray-900 border border-gray-800 rounded px-4 py-3">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className={`text-lg font-mono font-semibold ${isCount ? 'text-white' : value > 0 ? 'text-green-400' : value < 0 ? 'text-red-400' : 'text-gray-400'}`}>
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
