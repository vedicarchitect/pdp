import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/backtest')({
  component: BacktestPage,
})

function BacktestPage() {
  return <h1 className="text-2xl font-semibold">Backtest</h1>
}
