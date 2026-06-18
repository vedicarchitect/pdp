import { createFileRoute } from '@tanstack/react-router'
import { Card } from '@/components/ui/Card'
import { EventFeed } from '@/components/events/EventFeed'
import { EventConfigView } from '@/components/events/EventConfigView'
import { WebPushManager } from '@/components/events/WebPushManager'
import { Activity } from 'lucide-react'

export const Route = createFileRoute('/events')({
  component: EventsPage,
})

function EventsPage() {
  return (
    <div className="flex-1 space-y-4 p-4 md:p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Activity className="h-8 w-8 text-bullish" />
            Live Events
          </h2>
          <p className="text-text-muted mt-1">
            Real-time feed of market events, indicator triggers, and option walls.
          </p>
        </div>
        <div>
          <WebPushManager />
        </div>
      </div>

      <Card className="p-6">
        <h3 className="text-lg font-medium mb-4">Event Publisher Status</h3>
        <EventConfigView />
      </Card>

      <Card className="p-6">
        <EventFeed />
      </Card>
    </div>
  )
}
