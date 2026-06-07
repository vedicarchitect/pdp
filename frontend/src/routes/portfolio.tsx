import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/portfolio')({
  component: PortfolioPage,
})

function PortfolioPage() {
  return <h1 className="text-2xl font-semibold">Portfolio</h1>
}
