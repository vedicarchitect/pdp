import type { PositionalLeg } from '../../types/positional'
import { computeDTE } from '../../lib/utils'

interface ExpiryAlert {
  leg: PositionalLeg
  dte: number
}

function severity(dte: number): { label: string; classes: string } {
  if (dte <= 1) return { label: 'CRITICAL', classes: 'bg-red-950 border-red-700 text-red-200' }
  if (dte <= 3) return { label: 'URGENT', classes: 'bg-orange-950 border-orange-700 text-orange-200' }
  return { label: 'WARNING', classes: 'bg-yellow-950 border-yellow-700 text-yellow-200' }
}

function alertMessage(leg: PositionalLeg, dte: number): string {
  const name = leg.symbol ?? leg.security_id
  if (dte === 0) return `${name}: expires TODAY — action required`
  if (dte === 1) return `${name}: expires TOMORROW — action required`
  return `${name}: expires in ${dte} days — consider rolling`
}

interface Props {
  legs: PositionalLeg[]
}

export function ExpiryAlertPanel({ legs }: Props) {
  const alerts: ExpiryAlert[] = legs
    .filter((l) => l.expiry != null && l.net_qty !== 0)
    .map((l) => ({ leg: l, dte: computeDTE(l.expiry!) }))
    .filter((a) => a.dte <= 7)
    .sort((a, b) => a.dte - b.dte)

  if (alerts.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      {alerts.map(({ leg, dte }) => {
        const { label, classes } = severity(dte)
        return (
          <div
            key={`${leg.security_id}-expiry`}
            className={`flex items-center gap-2 px-3 py-2 rounded border text-xs font-medium ${classes}`}
          >
            <span className="font-bold">[{label}]</span>
            <span>{alertMessage(leg, dte)}</span>
          </div>
        )
      })}
    </div>
  )
}
