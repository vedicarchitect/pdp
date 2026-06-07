import { createRootRoute, Link, Outlet } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'
import Sidebar from '../components/Sidebar'
import ModeBanner from '../components/ModeBanner'

function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 mt-16">
      <h1 className="text-2xl font-semibold">404 — Page not found</h1>
      <Link to="/intraday" className="text-blue-400 hover:underline">
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
  return (
    <div className="flex flex-col min-h-screen">
      <ModeBanner />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
      {import.meta.env.DEV && <TanStackRouterDevtools />}
    </div>
  )
}
