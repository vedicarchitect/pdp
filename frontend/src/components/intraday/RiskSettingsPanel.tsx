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
    <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted bg-surface border border-surface-border rounded-lg px-4 py-2">
      {isLoading ? (
        <span className="text-text-subtle">Loading risk settings…</span>
      ) : (
        <>
          {isDefault && (
            <span className="px-2 py-0.5 bg-warning/10 border border-warning/30 rounded text-warning font-medium">
              ⚠ Using defaults
            </span>
          )}
          <span>
            Daily cap: <span className="font-mono text-text-main">₹{settings.RISK_DAILY_LOSS_CAP_INR.toLocaleString()}</span>
          </span>
          <span>
            Per-strategy cap: <span className="font-mono text-text-main">₹{settings.RISK_PER_STRATEGY_LOSS_CAP_INR.toLocaleString()}</span>
          </span>
          <span>
            Soft cap trigger: <span className="font-mono text-text-main">{settings.RISK_SOFT_CAP_PCT}%</span>
          </span>
          <span>
            Daily loss used:{' '}
            <span className={`font-mono font-medium ${pct >= 100 ? 'text-bearish' : pct >= 80 ? 'text-warning' : 'text-text-main'}`}>
              {pct.toFixed(1)}%
            </span>
          </span>
        </>
      )}
    </div>
  )
}
