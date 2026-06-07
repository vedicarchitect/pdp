import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/instruments')({
  component: InstrumentsPage,
})

function InstrumentsPage() {
  return <h1 className="text-2xl font-semibold">Instruments</h1>
}
