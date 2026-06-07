import type { RiskSettings } from '../../types/intraday'

interface Props {
  settings: RiskSettings
  isDefault: boolean
  isLoading: boolean
  dailyLoss: number
}

export function RiskSettingsPanel({ settings, isDefault, isLoading, dailyLoss }: Props) {
  const pct = settings.RISK_DAILY_LOSS_CAP_INR > 0
    ? (dailyLoss / settings.RISK_DAILY_LOSS_CAP_INR) * 100
    : 0

  return (
    <div className="flex items-center gap-4 text-xs text-gray-400 bg-gray-900 border border-gray-800 rounded px-4 py-2">
      {isLoading ? (
        <span className="text-gray-600">Loading risk settings…</span>
      ) : (
        <>
          {isDefault && (
            <span className="px-2 py-0.5 bg-yellow-900 border border-yellow-700 rounded text-yellow-400 font-medium">
              ⚠ Using defaults
            </span>
          )}
          <span>
            Daily cap: <span className="font-mono text-white">₹{settings.RISK_DAILY_LOSS_CAP_INR.toLocaleString()}</span>
          </span>
          <span>
            Per-strategy cap: <span className="font-mono text-white">₹{settings.RISK_PER_STRATEGY_LOSS_CAP_INR.toLocaleString()}</span>
          </span>
          <span>
            Soft cap trigger: <span className="font-mono text-white">{settings.RISK_SOFT_CAP_PCT}%</span>
          </span>
          <span>
            Daily loss used:{' '}
            <span className={`font-mono font-medium ${pct >= 80 ? 'text-yellow-400' : pct >= 100 ? 'text-red-400' : 'text-white'}`}>
              {pct.toFixed(1)}%
            </span>
          </span>
        </>
      )}
    </div>
  )
}
