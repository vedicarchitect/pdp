import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'
import { BarChart2, GitCompare, Play, Database, Trophy } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/Card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs'
import { StrategyForm } from '@/components/backtest/StrategyForm'
import { ResultsView } from '@/components/backtest/ResultsView'
import { RunsTable } from '@/components/backtest/RunsTable'
import { RunDetail } from '@/components/backtest/RunDetail'
import { WalkForwardView } from '@/components/backtest/WalkForwardView'
import { DayDrillDown } from '@/components/backtest/DayDrillDown'
import { CompareView } from '@/components/backtest/CompareView'
import { OptimizePanel } from '@/components/backtest/OptimizePanel'
import { OosLeaderboard } from '@/components/backtest/OosLeaderboard'
import { useToast } from '@/components/ui/Toast'
import type { BacktestRun } from '@/hooks/useStrangleBacktests'

export const Route = createFileRoute('/backtest')({
  component: BacktestPage,
})

async function runBacktest(payload: object) {
  const res = await fetch('/api/v1/backtests/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Backtest failed')
  }
  return res.json()
}

// ── Strangle warehouse view states ────────────────────────────────────────────

type WView =
  | { kind: 'list' }
  | { kind: 'detail'; run: BacktestRun }
  | { kind: 'walkforward'; run: BacktestRun }
  | { kind: 'day'; run: BacktestRun; date: string }
  | { kind: 'compare' }
  | { kind: 'optimize' }
  | { kind: 'leaderboard' }

function StrangleConsole() {
  const [view, setView] = useState<WView>({ kind: 'list' })
  const [compareIds, setCompareIds] = useState<string[]>([])

  function toggleCompare(id: string) {
    setCompareIds((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : ids.length >= 4 ? ids : [...ids, id],
    )
  }

  function removeCompare(id: string) {
    setCompareIds((ids) => ids.filter((x) => x !== id))
  }

  // Sub-nav bar (shown when not in list)
  const navCrumbs: Array<{ label: string; onClick: () => void }> = [
    { label: 'Runs', onClick: () => setView({ kind: 'list' }) },
  ]
  if (view.kind === 'detail') navCrumbs.push({ label: view.run.run_id.slice(0, 20) + '…', onClick: () => {} })
  if (view.kind === 'walkforward') {
    navCrumbs.push({ label: view.run.run_id.slice(0, 20) + '…', onClick: () => setView({ kind: 'detail', run: view.run }) })
    navCrumbs.push({ label: 'Walk-Forward', onClick: () => {} })
  }
  if (view.kind === 'day') {
    navCrumbs.push({ label: view.run.run_id.slice(0, 20) + '…', onClick: () => setView({ kind: 'detail', run: view.run }) })
    navCrumbs.push({ label: view.date, onClick: () => {} })
  }
  if (view.kind === 'compare') navCrumbs.push({ label: 'Compare', onClick: () => {} })
  if (view.kind === 'optimize') navCrumbs.push({ label: 'Optimize', onClick: () => {} })
  if (view.kind === 'leaderboard') navCrumbs.push({ label: 'Leaderboard', onClick: () => {} })

  return (
    <div className="flex flex-col gap-4" data-testid="strangle-console">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-xs text-text-muted">
          {navCrumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="opacity-40">›</span>}
              {i < navCrumbs.length - 1 ? (
                <button onClick={c.onClick} className="hover:text-text-main">{c.label}</button>
              ) : (
                <span className="text-text-main">{c.label}</span>
              )}
            </span>
          ))}
        </nav>

        {/* Action buttons */}
        <div className="flex gap-2">
          {compareIds.length >= 2 && view.kind !== 'compare' && (
            <button
              onClick={() => setView({ kind: 'compare' })}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-info/20 border border-info/30 rounded text-xs text-info hover:bg-info/30"
              data-testid="compare-btn"
            >
              <GitCompare size={12} />
              Compare {compareIds.length}
            </button>
          )}
          {view.kind === 'list' && (
            <>
              <button
                onClick={() => setView({ kind: 'leaderboard' })}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-card border border-surface-border rounded text-xs text-text-muted hover:text-text-main"
                data-testid="leaderboard-btn"
              >
                <Trophy size={12} />
                Leaderboard
              </button>
              <button
                onClick={() => setView({ kind: 'optimize' })}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-card border border-surface-border rounded text-xs text-text-muted hover:text-text-main"
                data-testid="optimize-btn"
              >
                <Play size={12} />
                Optimize
              </button>
            </>
          )}
          {view.kind === 'detail' && view.run.kind === 'walkforward' && (
            <button
              onClick={() => setView({ kind: 'walkforward', run: (view as { kind: 'detail'; run: BacktestRun }).run })}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-card border border-surface-border rounded text-xs text-text-muted hover:text-text-main"
              data-testid="walkforward-btn"
            >
              <BarChart2 size={12} />
              Walk-Forward
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      {view.kind === 'list' && (
        <RunsTable
          onSelect={(run) => setView({ kind: 'detail', run })}
          compareIds={compareIds}
          onToggleCompare={toggleCompare}
        />
      )}
      {view.kind === 'detail' && (
        <RunDetail
          run={view.run}
          onBack={() => setView({ kind: 'list' })}
          onSelectDay={(date) => setView({ kind: 'day', run: (view as { kind: 'detail'; run: BacktestRun }).run, date })}
        />
      )}
      {view.kind === 'walkforward' && (
        <WalkForwardView
          run={view.run}
          onBack={() => setView({ kind: 'detail', run: (view as { kind: 'walkforward'; run: BacktestRun }).run })}
        />
      )}
      {view.kind === 'day' && (
        <DayDrillDown
          run={(view as { kind: 'day'; run: BacktestRun; date: string }).run}
          date={(view as { kind: 'day'; run: BacktestRun; date: string }).date}
          onBack={() => setView({ kind: 'detail', run: (view as { kind: 'day'; run: BacktestRun; date: string }).run })}
        />
      )}
      {view.kind === 'compare' && (
        <CompareView
          runIds={compareIds}
          onRemove={removeCompare}
          onBack={() => setView({ kind: 'list' })}
        />
      )}
      {view.kind === 'optimize' && (
        <OptimizePanel onJobLaunched={() => setView({ kind: 'list' })} />
      )}
      {view.kind === 'leaderboard' && (
        <OosLeaderboard onSelect={(run) => setView({ kind: 'detail', run })} />
      )}
    </div>
  )
}

// ── Legacy options backtester ─────────────────────────────────────────────────

function OptionsBacktester() {
  const { toast } = useToast()
  const [results, setResults] = useState<object | null>(null)

  const mutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: (data) => {
      setResults(data)
      toast({ variant: 'success', title: 'Backtest complete', description: `${data.summary?.total_trades ?? 0} trades` })
    },
    onError: (err: Error) => {
      toast({ variant: 'error', title: 'Backtest failed', description: err.message })
    },
  })

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-6 items-start">
      <StrategyForm onSubmit={(p) => mutation.mutate(p)} isLoading={mutation.isPending} />
      <div className="flex flex-col gap-4">
        {mutation.isPending && (
          <Card>
            <CardContent className="flex items-center justify-center py-16">
              <div className="flex flex-col items-center gap-3 text-text-muted">
                <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
                <p className="text-sm">Running backtest…</p>
              </div>
            </CardContent>
          </Card>
        )}
        {mutation.isError && !mutation.isPending && (
          <Card>
            <CardContent className="py-8 text-center">
              <p className="text-sm text-bearish mb-2">{mutation.error.message}</p>
              <p className="text-xs text-text-muted">Check the API is running and data is available for the selected date range.</p>
            </CardContent>
          </Card>
        )}
        {results && !mutation.isPending && <ResultsView results={results as any} />}
        {!results && !mutation.isPending && !mutation.isError && (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-20 gap-3 text-text-muted">
              <BarChart2 size={40} className="opacity-20" />
              <p className="text-sm">Configure a strategy and click Run Backtest</p>
              <p className="text-xs opacity-60">Uses the MongoDB options warehouse — ensure data is backfilled for your date range.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

function BacktestPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <BarChart2 size={22} className="text-primary" />
        <h1 className="text-2xl font-bold text-text-main tracking-tight">Backtest Console</h1>
      </div>

      <Tabs defaultValue="strangle">
        <TabsList>
          <TabsTrigger value="strangle" data-testid="tab-strangle">
            <Database size={13} className="mr-1.5" />
            Strangle Warehouse
          </TabsTrigger>
          <TabsTrigger value="options" data-testid="tab-options">
            <BarChart2 size={13} className="mr-1.5" />
            Options Replay
          </TabsTrigger>
        </TabsList>

        <TabsContent value="strangle" className="mt-4">
          <StrangleConsole />
        </TabsContent>

        <TabsContent value="options" className="mt-4">
          <OptionsBacktester />
        </TabsContent>
      </Tabs>
    </div>
  )
}
