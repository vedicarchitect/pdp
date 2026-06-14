import { useEffect, useState } from 'react'
import type { Alert, AlertType, Position, PnLSummary, RiskSettings } from '../../types/intraday'

const STORAGE_KEY = 'intraday_dismissed_alerts'
const ALERT_TTL_MS = 60 * 60 * 1000 // alerts auto-expire after 1 hour

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as Array<[string, number]>
    const now = Date.now()
    return new Set(arr.filter(([, ts]) => now - ts < ALERT_TTL_MS).map(([id]) => id))
  } catch {
    return new Set()
  }
}

function saveDismissed(ids: Set<string>) {
  const now = Date.now()
  const arr: Array<[string, number]> = Array.from(ids).map((id) => [id, now])
  localStorage.setItem(STORAGE_KEY, JSON.stringify(arr))
}

function alertTypeColor(type: AlertType): string {
  switch (type) {
    case 'price': return 'bg-blue-900 border-blue-600 text-blue-200'
    case 'pnl': return 'bg-orange-900 border-orange-600 text-orange-200'
    case 'time': return 'bg-purple-900 border-purple-600 text-purple-200'
  }
}

function alertTypeIcon(type: AlertType): string {
  switch (type) {
    case 'price': return '📈'
    case 'pnl': return '💰'
    case 'time': return '⏱'
  }
}

interface Props {
  positions: Position[]
  summary: PnLSummary | null
  settings: RiskSettings | null
}

function buildAlerts(positions: Position[], summary: PnLSummary | null, settings: RiskSettings | null): Alert[] {
  const alerts: Alert[] = []
  const now = Date.now()

  // Time-stop: positions open for more than 4 hours
  for (const pos of positions) {
    if (pos.net_qty === 0 || !pos.updated_at) continue
    const openedAt = new Date(pos.updated_at).getTime()
    if (now - openedAt > 4 * 60 * 60 * 1000) {
      alerts.push({
        id: `time-${pos.security_id}`,
        type: 'time',
        message: `${pos.security_id}: position open for >4 hours`,
        timestamp: now,
        security_id: pos.security_id,
      })
    }
  }

  // P&L alert: per-strategy loss approaching per-strategy cap
  if (settings) {
    const perStrategyCap = settings.RISK_PER_STRATEGY_LOSS_CAP_INR
    const stratMap = new Map<string, number>()
    for (const pos of positions) {
      const sid = pos.strategy_id ?? 'Ungrouped'
      const loss = -((pos.realized_pnl + pos.unrealized_pnl))
      stratMap.set(sid, (stratMap.get(sid) ?? 0) + loss)
    }
    for (const [sid, loss] of stratMap) {
      if (loss > perStrategyCap * 0.8) {
        alerts.push({
          id: `pnl-strategy-${sid}`,
          type: 'pnl',
          message: `Strategy ${sid}: loss ₹${loss.toFixed(0)} approaching per-strategy cap ₹${perStrategyCap.toFixed(0)}`,
          timestamp: now,
          strategy_id: sid,
        })
      }
    }
  }

  // Daily P&L alert: approaching soft cap
  if (summary && settings) {
    const pct = summary.realized_loss_today / settings.RISK_DAILY_LOSS_CAP_INR
    if (pct >= settings.RISK_SOFT_CAP_PCT / 100 && pct < 1.0) {
      alerts.push({
        id: `pnl-daily-${Math.floor(Date.now() / 300_000)}`, // bucket by 5min to avoid re-alerting every tick
        type: 'pnl',
        message: `Daily loss: ₹${summary.realized_loss_today.toFixed(0)} (${(pct * 100).toFixed(0)}% of cap)`,
        timestamp: now,
      })
    }
  }

  return alerts
}

export function AlertPills({ positions, summary, settings }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissed())
  const alerts = buildAlerts(positions, summary, settings).filter((a) => !dismissed.has(a.id))

  useEffect(() => {
    saveDismissed(dismissed)
  }, [dismissed])

  function dismiss(id: string) {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }

  if (alerts.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className={`flex items-center gap-2 px-3 py-1.5 rounded border text-xs font-medium ${alertTypeColor(alert.type)}`}
        >
          <span>{alertTypeIcon(alert.type)}</span>
          <span>{alert.message}</span>
          <button
            onClick={() => dismiss(alert.id)}
            className="ml-1 text-current opacity-60 hover:opacity-100 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current"
            aria-label="Dismiss alert"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
