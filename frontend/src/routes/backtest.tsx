import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'
import { BarChart2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/Card'
import { StrategyForm } from '@/components/backtest/StrategyForm'
import { ResultsView } from '@/components/backtest/ResultsView'
import { useToast } from '@/components/ui/Toast'

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

function BacktestPage() {
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
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <BarChart2 size={22} className="text-primary" />
        <h1 className="text-2xl font-bold text-text-main tracking-tight">Options Strategy Backtester</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-6 items-start">
        {/* Left: strategy form */}
        <StrategyForm onSubmit={(p) => mutation.mutate(p)} isLoading={mutation.isPending} />

        {/* Right: results */}
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

          {results && !mutation.isPending && (
            <ResultsView results={results as any} />
          )}

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
    </div>
  )
}
