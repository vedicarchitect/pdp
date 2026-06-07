# Frontend Shell — Spec

## Requirements

### Requirement: Vite + React scaffold initialised
The system SHALL provide a working `frontend/` directory containing a Vite + React 19 + TypeScript project that builds successfully (`pnpm build` exits 0).

#### Scenario: Clean build succeeds
- **WHEN** `pnpm build` is run inside `frontend/`
- **THEN** the command exits with code 0 and emits a `dist/` directory

#### Scenario: Dev server starts
- **WHEN** `pnpm dev` is run inside `frontend/`
- **THEN** the Vite dev server starts on port 5173 and serves the root HTML

---

### Requirement: Six route stubs registered
The system SHALL register the following routes via TanStack Router, each rendering a placeholder page component with the route name as its heading: `/intraday`, `/positional`, `/portfolio`, `/strategies`, `/backtest`, `/instruments`.

#### Scenario: Root redirects to /intraday
- **WHEN** the user navigates to `/`
- **THEN** the router redirects to `/intraday`

#### Scenario: Each route renders its stub
- **WHEN** the user navigates to any of the six routes
- **THEN** the page renders a heading containing the route name and no JavaScript errors appear in the console

#### Scenario: Unknown route shows 404 stub
- **WHEN** the user navigates to an unregistered path
- **THEN** a catch-all NotFound component is rendered (wired via `notFoundComponent` on the root route)

---

### Requirement: Navigation sidebar present
The system SHALL render a persistent left navigation sidebar listing all six routes. The active route SHALL be visually highlighted.

#### Scenario: Sidebar visible on all routes
- **WHEN** the user navigates to any registered route
- **THEN** the sidebar is visible and contains links to all six routes

#### Scenario: Active link highlighted
- **WHEN** the current route is `/portfolio`
- **THEN** the Portfolio link in the sidebar has an active style distinct from other links

---

### Requirement: TanStack Query provider configured
The system SHALL wrap the application in a `QueryClientProvider` so that any route component may call `useQuery` without additional setup.

#### Scenario: Query client available in route component
- **WHEN** a route component calls `useQuery({ queryKey: ['test'], queryFn: async () => 'ok' })`
- **THEN** the query resolves successfully without a "no QueryClient" error

---

### Requirement: WebSocket hooks implemented
The system SHALL export four hooks from `frontend/src/hooks/`:

- `useMarketWS(securityIds: string[])` — subscribes to `/ws/market` and emits tick objects
- `useLTP(securityId: string)` — returns the latest trade price for one security
- `usePnL()` — subscribes to `/ws/portfolio` and returns the current P&L summary
- `useOrderStream()` — subscribes to `/ws/orders` and returns the latest order update

Each hook SHALL reconnect automatically with exponential back-off (1 s → 2 s → 4 s → 8 s, cap 30 s) when the WebSocket closes unexpectedly. All hooks respect the `VITE_WS_DISABLED=true` env flag to return stubs without opening connections.

#### Scenario: useMarketWS reconnects after disconnect
- **WHEN** the `/ws/market` WebSocket is closed by the server
- **THEN** the hook attempts reconnection after 1 s, then 2 s, then 4 s

#### Scenario: useLTP returns undefined before first tick
- **WHEN** `useLTP("NSE:NIFTY")` is called before any tick arrives
- **THEN** the return value is `undefined`

#### Scenario: usePnL emits summary on portfolio update
- **WHEN** the `/ws/portfolio` feed sends a `portfolio_update` message with a `summary` field
- **THEN** `usePnL()` returns an object with `total_realized_pnl`, `total_unrealized_pnl`, and `realized_loss_today`

#### Scenario: VITE_WS_DISABLED stub
- **WHEN** `VITE_WS_DISABLED=true` is set in the environment
- **THEN** all four hooks return stub/empty data without opening any WebSocket connections

---

### Requirement: lightweight-charts charting placeholder
The system SHALL export a `CandleChart` component from `frontend/src/components/CandleChart.tsx` that renders an empty `lightweight-charts` chart container. The component SHALL accept a `title` prop.

#### Scenario: Chart renders without data
- **WHEN** `<CandleChart title="NIFTY" />` is rendered
- **THEN** a chart container div is present in the DOM with no JavaScript errors

---

### Requirement: PAPER / LIVE mode banner
The system SHALL display a persistent top banner indicating the current trade mode.

The mode is determined by intercepting the `X-Trade-Mode` response header from any `fetch` call (via a global fetch wrapper installed in `main.tsx`). If the header is absent, the banner defaults to `PAPER`.

- `paper` → yellow banner with text "PAPER MODE — trades are simulated"
- `live` → red banner with text "LIVE MODE — real money at risk"

#### Scenario: Banner defaults to PAPER when header absent
- **WHEN** no API call has been made or the `X-Trade-Mode` header is not present
- **THEN** the yellow PAPER banner is displayed

#### Scenario: Banner switches to LIVE on header
- **WHEN** any `fetch` response carries `X-Trade-Mode: live`
- **THEN** the banner switches to red LIVE mode

---

### Requirement: Vite dev proxy configured
The system SHALL configure the Vite dev server to proxy `/api` requests to `http://localhost:8000` and upgrade `/ws` connections to `ws://localhost:8000`.

#### Scenario: API call proxied in dev
- **WHEN** the frontend calls `/api/v1/settings/risk` during development
- **THEN** the request is forwarded to `http://localhost:8000/api/v1/settings/risk`

#### Scenario: WebSocket upgraded in dev
- **WHEN** a hook opens `ws://localhost:5173/ws/portfolio` during development
- **THEN** the Vite proxy upgrades and forwards the connection to `ws://localhost:8000/ws/portfolio`

---

### Requirement: shadcn/ui + utility infrastructure
The system SHALL provide shadcn/ui component infrastructure: `components.json`, `src/lib/utils.ts` (with `cn()` helper), and installed runtime packages (`clsx`, `tailwind-merge`, `class-variance-authority`, `lucide-react`). Individual shadcn components are added per-feature via `pnpm dlx shadcn add <component>`.
