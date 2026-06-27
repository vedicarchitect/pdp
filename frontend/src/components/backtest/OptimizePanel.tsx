import { useState } from 'react'
import { Play, Loader2, BarChart2 } from 'lucide-react'
import { useLaunchWalkforward } from '@/hooks/useStrangleBacktests'
import { Card, CardContent } from '@/components/ui/Card'
import { useToast } from '@/components/ui/Toast'
import { useJobWS } from '@/hooks/useJobWS'

interface Props {
  onJobLaunched?: (jobId: string) => void
}

export function OptimizePanel({ onJobLaunched }: Props) {
  const [dateFrom, setDateFrom] = useState('2021-06-01')
  const [dateTo, setDateTo] = useState('2026-05-31')
  const [isMonths, setIsMonths] = useState(12)
  const [oosMonths, setOosMonths] = useState(3)
  const [objective, setObjective] = useState('sharpe')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  const launchWf = useLaunchWalkforward()
  const { toast } = useToast()

  // Live progress WS for active job
  const jobProgress = useJobWS(activeJobId)

  function handleLaunch() {
    launchWf.mutate(
      {
        config: {},
        date_from: dateFrom,
        date_to: dateTo,
        is_months: isMonths,
        oos_months: oosMonths,
        objective,
        mongo: true,
      },
      {
        onSuccess: (r) => {
          setActiveJobId(r.job_id)
          onJobLaunched?.(r.job_id)
          toast({ variant: 'success', title: 'Walk-forward launched', description: `Job ${r.job_id.slice(0, 8)}` })
        },
        onError: (e: Error) => toast({ variant: 'error', title: 'Launch failed', description: e.message }),
      },
    )
  }

  const isRunning = launchWf.isPending || (activeJobId != null && jobProgress.progress < 100)
  const progress = jobProgress.progress

  return (
    <div className="flex flex-col gap-4" data-testid="optimize-panel">
      <div className="flex items-center gap-2">
        <BarChart2 size={16} className="text-primary" />
        <p className="text-sm font-medium text-text-main">Launch Walk-Forward Optimization</p>
      </div>

      <Card>
        <CardContent className="pt-4 flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">From</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="bg-surface-bg border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">To</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-surface-bg border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">IS months</span>
              <input
                type="number"
                value={isMonths}
                onChange={(e) => setIsMonths(Number(e.target.value))}
                min={3}
                className="bg-surface-bg border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">OOS months</span>
              <input
                type="number"
                value={oosMonths}
                onChange={(e) => setOosMonths(Number(e.target.value))}
                min={1}
                className="bg-surface-bg border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-text-muted">Objective</span>
            <select
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              className="bg-surface-bg border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none"
            >
              <option value="sharpe">Sharpe</option>
              <option value="calmar">Calmar</option>
              <option value="pf">Profit Factor</option>
              <option value="net">Net P&L</option>
            </select>
          </label>
          <button
            onClick={handleLaunch}
            disabled={isRunning}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-primary text-white rounded font-medium text-sm disabled:opacity-50"
          >
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {isRunning ? 'Running…' : 'Launch Walk-Forward'}
          </button>

          {/* Progress bar */}
          {activeJobId && (
            <div className="flex flex-col gap-1">
              <div className="flex justify-between text-xs text-text-muted">
                <span>Job {activeJobId.slice(0, 8)}</span>
                <span>{progress}%</span>
              </div>
              <div className="h-1.5 bg-surface-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              {jobProgress.message && (
                <p className="text-xs text-text-muted truncate">{jobProgress.message}</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
