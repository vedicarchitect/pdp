import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/strategies')({
  component: StrategiesPage,
})

function StrategiesPage() {
  return <h1 className="text-2xl font-semibold">Strategies</h1>
}
