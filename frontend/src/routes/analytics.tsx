import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { MaxPainChart } from '../components/analytics/MaxPainChart'
import { GEXChart } from '../components/analytics/GEXChart'
import { OIHeatmap } from '../components/analytics/OIHeatmap'

export const Route = createFileRoute('/analytics')({
  component: AnalyticsPage,
})

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY'] as const
type Underlying = (typeof UNDERLYINGS)[number]

function AnalyticsPage() {
  const [underlying, setUnderlying] = useState<Underlying>('NIFTY')
  const [expiry, setExpiry] = useState<string | undefined>(undefined)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Options Analytics</h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <label className="text-sm text-text-muted">Underlying</label>
            <select
              value={underlying}
              onChange={(e) => {
                setUnderlying(e.target.value as Underlying)
                setExpiry(undefined)
              }}
              className="text-sm bg-surface border border-surface-border rounded-md px-2 py-1 text-text-main focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {UNDERLYINGS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-text-muted">Expiry</label>
            <input
              type="date"
              value={expiry ?? ''}
              onChange={(e) => setExpiry(e.target.value || undefined)}
              className="text-sm bg-surface border border-surface-border rounded-md px-2 py-1 text-text-main focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-surface border border-surface-border rounded-xl p-4">
          <h2 className="text-base font-semibold mb-3">Max Pain</h2>
          <MaxPainChart underlying={underlying} expiry={expiry} />
        </div>

        <div className="bg-surface border border-surface-border rounded-xl p-4">
          <h2 className="text-base font-semibold mb-3">Gamma Exposure (GEX)</h2>
          <GEXChart underlying={underlying} expiry={expiry} />
        </div>
      </div>

      <div className="bg-surface border border-surface-border rounded-xl p-4">
        <h2 className="text-base font-semibold mb-3">OI Heatmap &amp; PCR</h2>
        <OIHeatmap underlying={underlying} expiry={expiry} />
      </div>
    </div>
  )
}
