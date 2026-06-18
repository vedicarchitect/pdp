import { createFileRoute } from '@tanstack/react-router'
import { Card } from '@/components/ui/Card'
import { AlertsList } from '@/components/alerts/AlertsList'

export const Route = createFileRoute('/alerts')({
  component: AlertsPage,
})

function AlertsPage() {
  return (
    <div className="flex-1 space-y-4 p-4 md:p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">Alerts</h2>
      </div>

      <Card className="p-6">
        <AlertsList />
      </Card>
    </div>
  )
}
