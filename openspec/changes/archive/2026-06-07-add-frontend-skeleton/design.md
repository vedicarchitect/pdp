## Context

PDP is a backend-first trading platform (FastAPI + PostgreSQL + Redis + MongoDB). There is currently no frontend — the UI layer is entirely absent. The backend exposes REST endpoints under `/api/v1/` and three WebSocket feeds (`/ws/market`, `/ws/orders`, `/ws/portfolio`). The intraday monitor change (`add-intraday-monitor`) requires a frontend shell to be in place before its UI tasks (4–9) can proceed.

This change scaffolds the frontend as a standalone Vite + React SPA under `frontend/`. No backend code changes are required.

## Goals / Non-Goals

**Goals:**
- Create `frontend/` directory with a working Vite + React 19 + TypeScript scaffold
- Wire TanStack Router with all six route stubs (`/intraday`, `/positional`, `/portfolio`, `/strategies`, `/backtest`, `/instruments`)
- Install and configure TanStack Query, shadcn/ui, and Tailwind 4
- Implement four WebSocket hooks: `useMarketWS`, `useLTP`, `usePnL`, `useOrderStream`
- Add a charting placeholder via `lightweight-charts`
- Add a global `PAPER` / `LIVE` mode banner driven by `X-Trade-Mode` response header

**Non-Goals:**
- Real data wiring to live backend APIs (route stubs only)
- Authentication / login flow
- Production build pipeline or Docker image
- End-to-end test suite for the frontend
- Mobile / responsive layout optimization

## Decisions

### Vite over Next.js or CRA
PDP is a trading dashboard — no server-side rendering or SEO required. Vite provides the fastest HMR and smallest config surface. CRA is deprecated. Next.js SSR adds complexity without benefit.

### TanStack Router over React Router v6
TanStack Router generates fully type-safe route trees. This eliminates silent runtime errors from string-typed `useParams` / `useNavigate` calls — important in a trading context where wrong routing can show stale data. Trade-off: requires route-file convention and a small code-gen step (`tsr generate`), but this is acceptable for a scaffold change.

### TanStack Query for server state
REST calls (portfolio snapshot, risk settings, strategy list) are read-heavy with infrequent mutations. TanStack Query handles caching, stale-while-revalidate, and error retries without Redux boilerplate. WebSocket state is managed separately in hooks.

### shadcn/ui + Tailwind 4
shadcn/ui components are unstyled primitives that ship as local source files — no upstream version lock-in. Tailwind 4's CSS-first config reduces the `tailwind.config.js` surface. Trade-off: Tailwind 4 is relatively new; minor breaking changes are possible during scaffold but the project is greenfield so migration cost is zero.

### lightweight-charts for charting
TradingView's `lightweight-charts` is MIT-licensed, WebGL-accelerated, and designed specifically for financial time series. Alternatives (Recharts, Victory) are not optimized for tick-level data. Charting is scaffold-only in this change — actual data wiring comes later.

### `X-Trade-Mode` header for PAPER/LIVE banner
The backend `Settings.LIVE` flag is reflected in API responses. Reading a custom header (`X-Trade-Mode: paper|live`) via a TanStack Query `meta` interceptor lets the banner update on any API call without a dedicated endpoint. This avoids adding a `/api/v1/mode` route.

## Risks / Trade-offs

- **Tailwind 4 compatibility** — PostCSS plugin API changed in v4; if any shadcn/ui component uses Tailwind v3-only syntax it may break. Mitigation: pin exact Tailwind and shadcn versions at scaffold time; run `pnpm build` in CI.
- **TanStack Router code-gen** — `tsr generate` must run before `tsc` or imports fail. Mitigation: add `"prebuild": "tsr generate"` to `package.json` and document in README.
- **WebSocket hooks reconnect complexity** — hooks implement exponential back-off; if the backend is not running during development, the browser console will fill with reconnect warnings. Mitigation: add a `VITE_WS_DISABLED=true` env flag that stubs the hooks.
- **CORS** — Vite dev server proxies `/api` and `/ws` to `localhost:8000`. Production deployment must configure the FastAPI CORS middleware or a reverse proxy.
