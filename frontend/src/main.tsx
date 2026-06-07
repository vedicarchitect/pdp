import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { routeTree } from './routeTree.gen'
import { extractTradeModeFromResponse } from './hooks/useTradeMode'
import './index.css'

// Intercept all fetch calls to pick up X-Trade-Mode header for the mode banner.
// Headers are read-only (no body consumed), so no clone is needed.
const _fetch = globalThis.fetch.bind(globalThis)
globalThis.fetch = async (...args: Parameters<typeof fetch>) => {
  const res = await _fetch(...args)
  extractTradeModeFromResponse(res)
  return res
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
    },
  },
})

const router = createRouter({
  routeTree,
  context: {},
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  </StrictMode>,
)
