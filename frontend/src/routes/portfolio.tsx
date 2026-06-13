import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/portfolio')({
  component: PortfolioPage,
})

function PortfolioPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-text-main tracking-tight">Portfolio</h1>
      <div className="glass-panel rounded-xl p-8 text-center text-text-muted">
        Portfolio feature is under construction.
      </div>
    </div>
  )
}
