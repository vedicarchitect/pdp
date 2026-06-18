import type { PnLSummary, RiskSettings } from '../../types/intraday'

interface Props {
  summary: PnLSummary | null
  settings: RiskSettings | null
}

export function RiskBanner({ summary, settings }: Props) {
  if (!summary || !settings) return null

  const loss = summary.realized_loss_today
  const cap = settings.RISK_DAILY_LOSS_CAP_INR
  const softPct = settings.RISK_SOFT_CAP_PCT / 100
  const pct = cap > 0 ? loss / cap : 0

  if (pct <= softPct) return null

  if (pct >= 1.5) {
    return (
      <div className="w-full bg-bearish/15 border border-bearish/50 rounded-lg px-4 py-2 text-bearish text-sm font-medium flex items-center gap-2">
        <span>⚠</span>
        CRITICAL: Daily loss at {(pct * 100).toFixed(0)}% of daily cap — hard cap triggered. All positions being flattened.
        <span className="ml-auto font-mono">₹{loss.toFixed(0)} / ₹{cap.toFixed(0)}</span>
      </div>
    )
  }

  if (pct >= 1.0) {
    return (
      <div className="w-full bg-bearish/10 border border-bearish/40 rounded-lg px-4 py-2 text-bearish text-sm font-medium flex items-center gap-2">
        <span>🔴</span>
        Loss cap breached — automatic kill-switch may trigger.
        <span className="ml-auto font-mono">₹{loss.toFixed(0)} / ₹{cap.toFixed(0)}</span>
      </div>
    )
  }

  return (
    <div className="w-full bg-warning/10 border border-warning/40 rounded-lg px-4 py-2 text-warning text-sm font-medium flex items-center gap-2">
      <span>⚠</span>
      Approaching loss cap: {(pct * 100).toFixed(0)}% of daily limit used.
      <span className="ml-auto font-mono">₹{loss.toFixed(0)} / ₹{cap.toFixed(0)}</span>
    </div>
  )
}
