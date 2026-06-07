import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/positional')({
  component: PositionalPage,
})

function PositionalPage() {
  return <h1 className="text-2xl font-semibold">Positional</h1>
}
