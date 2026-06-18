import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'
import Sidebar from '../components/Sidebar'
import { useAlertsWS } from '../hooks/useAlertsWS'
import { useEventsWS } from '../hooks/useEventsWS'
import { ToastProvider } from '@/components/ui/Toast'

function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 mt-16">
      <h1 className="text-2xl font-semibold text-text-main">404 — Page not found</h1>
      <Link to="/intraday" className="text-primary hover:text-primary/80 transition-colors">
        Go to Intraday
      </Link>
    </div>
  )
}

export const Route = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFound,
})

function RootLayout() {
  useAlertsWS()
  useEventsWS()

  return (
    <ToastProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto min-w-0">
          <Outlet />
        </main>
      </div>
      {import.meta.env.DEV && <TanStackRouterDevtools />}
    </ToastProvider>
  )
}
