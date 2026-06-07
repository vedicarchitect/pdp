## 1. Project Scaffold

- [x] 1.1 Run `pnpm create vite frontend --template react-ts` from repo root to initialise the Vite + React 19 + TypeScript project
- [x] 1.2 Install core dependencies: `pnpm add @tanstack/react-router @tanstack/react-query tailwindcss@next @tailwindcss/vite shadcn lightweight-charts`
- [x] 1.3 Install dev dependencies: `pnpm add -D @tanstack/router-devtools @tanstack/react-query-devtools typescript @types/react @types/react-dom`
- [x] 1.4 Configure `vite.config.ts`: add `@tailwindcss/vite` plugin and dev proxy (`/api` → `http://localhost:8000`, `/ws` → `ws://localhost:8000` with `ws: true`)
- [x] 1.5 Initialise Tailwind 4 (`tailwind.css` import) and verify `pnpm build` exits 0

## 2. Routing

- [x] 2.1 Create `frontend/src/routes/__root.tsx` with the root layout (sidebar + main slot + mode banner)
- [x] 2.2 Create stub route files: `routes/intraday.tsx`, `routes/positional.tsx`, `routes/portfolio.tsx`, `routes/strategies.tsx`, `routes/backtest.tsx`, `routes/instruments.tsx` — each renders a heading with the route name
- [x] 2.3 Create `routes/index.tsx` that redirects to `/intraday`
- [x] 2.4 Create `routes/notFound.tsx` catch-all page
- [x] 2.5 Create `frontend/src/routeTree.gen.ts` via `pnpm tsr generate` (or manual route tree if code-gen unavailable)
- [x] 2.6 Add `"prebuild": "tsr generate"` to `frontend/package.json` scripts

## 3. Navigation Sidebar

- [x] 3.1 Create `frontend/src/components/Sidebar.tsx` listing all six routes with TanStack Router `<Link>` components
- [x] 3.2 Apply active-link styles using TanStack Router's `activeProps` / `inactiveProps` or `data-status` attribute
- [x] 3.3 Mount `<Sidebar>` inside the root layout (`__root.tsx`)

## 4. TanStack Query Provider

- [x] 4.1 Create `frontend/src/main.tsx` wrapping `<RouterProvider>` inside `<QueryClientProvider client={queryClient}>`
- [x] 4.2 Add `ReactQueryDevtools` and `TanStackRouterDevtools` in dev mode only

## 5. WebSocket Hooks

- [x] 5.1 Create `frontend/src/hooks/useMarketWS.ts` — opens `/ws/market`, emits tick objects, implements exponential back-off reconnect (1 s → 2 s → 4 s → 8 s, cap 30 s)
- [x] 5.2 Create `frontend/src/hooks/useLTP.ts` — wraps `useMarketWS` for a single security ID, returns latest LTP or `undefined`
- [x] 5.3 Create `frontend/src/hooks/usePnL.ts` — opens `/ws/portfolio`, returns P&L summary (`total_realized_pnl`, `total_unrealized_pnl`, `realized_loss_today`)
- [x] 5.4 Create `frontend/src/hooks/useOrderStream.ts` — opens `/ws/orders`, returns latest order update object
- [x] 5.5 Add `VITE_WS_DISABLED` env guard to all four hooks: when `true`, skip WebSocket creation and return stub/empty values
- [x] 5.6 Export all four hooks from `frontend/src/hooks/index.ts`

## 6. Charting Placeholder

- [x] 6.1 Create `frontend/src/components/CandleChart.tsx` that mounts a `lightweight-charts` `createChart()` container in a `useEffect`, accepts a `title: string` prop, and cleans up on unmount
- [x] 6.2 Add `<CandleChart title="NIFTY" />` to the Intraday stub page to verify it renders without errors

## 7. Trade Mode Banner

- [x] 7.1 Create `frontend/src/hooks/useTradeMode.ts` — reads `X-Trade-Mode` header from TanStack Query responses via a custom `QueryClient` `defaultOptions.queries.onSuccess` meta hook; stores mode in module-level state (default: `"paper"`)
- [x] 7.2 Create `frontend/src/components/ModeBanner.tsx` — renders a full-width banner: yellow for `paper`, red for `live`, with the appropriate message text
- [x] 7.3 Mount `<ModeBanner>` at the top of the root layout, above the sidebar + main area

## 8. Final Verification

- [x] 8.1 Run `pnpm build` inside `frontend/` and confirm exit 0 with no TypeScript errors
- [x] 8.2 Run `pnpm dev`, open browser at `http://localhost:5173`, verify root redirects to `/intraday`, sidebar is visible, and all six routes render their stub headings
- [x] 8.3 Add `frontend/` to `.gitignore` exclusions for `node_modules` and `dist` (if not already present via `.gitignore` at repo root)
