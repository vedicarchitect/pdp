import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { MaxPainChart } from '@/components/analytics/MaxPainChart'
import { GEXChart } from '@/components/analytics/GEXChart'
import { OIHeatmap } from '@/components/analytics/OIHeatmap'
import { OIBuildupPanel } from '@/components/analytics/OIBuildupPanel'
import { MultiStrikeOIChart } from '@/components/analytics/MultiStrikeOIChart'
import { StraddleHistoryChart } from '@/components/analytics/StraddleHistoryChart'
import { IVRankGauge } from '@/components/analytics/IVRankGauge'
import { FIIDIIPanel } from '@/components/analytics/FIIDIIPanel'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'

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
            <select
              value={expiry ?? ''}
              onChange={(e) => setExpiry(e.target.value || undefined)}
              className="bg-surface border border-surface-border text-text-main text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary w-full"
            >
              <option value="">Nearest Expiry</option>
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-12">
          <FIIDIIPanel />
        </div>
        
        <div className="lg:col-span-8">
          <OIBuildupPanel underlying={underlying} />
        </div>
        <div className="lg:col-span-4 flex flex-col gap-6">
          <IVRankGauge underlying={underlying} />
          <StraddleHistoryChart underlying={underlying} />
        </div>
        
        <div className="lg:col-span-12">
          <MultiStrikeOIChart underlying={underlying} />
        </div>
        
        <div className="lg:col-span-8">
          <Card>
            <CardHeader><CardTitle>Max Pain</CardTitle></CardHeader>
            <CardContent>
              <MaxPainChart underlying={underlying} expiry={expiry || undefined} />
            </CardContent>
          </Card>
        </div>
        <div className="lg:col-span-4">
          <Card>
            <CardHeader><CardTitle>Gamma Exposure (GEX)</CardTitle></CardHeader>
            <CardContent>
              <GEXChart underlying={underlying} expiry={expiry || undefined} />
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>OI Heatmap &amp; PCR</CardTitle></CardHeader>
        <CardContent>
          <OIHeatmap underlying={underlying} expiry={expiry || undefined} />
        </CardContent>
      </Card>
    </div>
  )
}
