import { createFileRoute } from '@tanstack/react-router'
import { BuilderPanel } from '../components/builder/BuilderPanel'

export const Route = createFileRoute('/builder')({
  component: BuilderRoute,
})

function BuilderRoute() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-text-main tracking-tight">Strategy Builder</h1>
      <BuilderPanel />
    </div>
  )
}
