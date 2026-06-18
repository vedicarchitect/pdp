# Frontend

## Core Philosophy

**Speed · Quality · Clean UI — no compromise on any of the three.**

- **Speed**: Zero-overhead hot path. TanStack Query caching over redundant fetches. Recharts/lightweight-charts for performant visualisation. No synchronous I/O or blocking renders.
- **Quality**: TypeScript strict mode. Every component typed. No `any` unless wrapping an untyped external API. CVA for variant safety.
- **Clean UI**: Consistent design tokens from `index.css @theme`. Every visual surface uses the `components/ui/` kit — no ad-hoc inline styles. Pixel-perfect dark mode.

## Stack

Vite + React 19 + TanStack Router + TanStack Query + CVA component library + TypeScript

```bash
cd frontend && npm run dev         # Vite dev server (:5173)
cd frontend && npm run build       # production bundle
cd frontend && npx tsc --noEmit    # type check only
cd frontend && npm test            # vitest unit tests
cd frontend && npx playwright test # e2e UI verification (required after every frontend change)
```

## Structure

```
frontend/src/
├── routes/              # TanStack Router file-based routes
│   ├── __root.tsx       # Root layout: ToastProvider, Sidebar, Outlet
│   ├── index.tsx        # Dashboard /
│   └── ...              # analytics, portfolio, instruments, backtest, events, ...
├── components/
│   ├── ui/              # CVA primitive library — Button, Card, Badge, DataTable,
│   │                    # Dialog (ARIA + focus-trap), Toast/useToast, Tabs, Select,
│   │                    # Input, NumberField, Switch, Skeleton, Tooltip
│   ├── analytics/       # GEXChart, MaxPainChart, OIHeatmap (use chartTheme)
│   ├── intraday/        # PositionTable, RiskBanner, AlertPills, RiskSettingsPanel
│   ├── positional/      # StrategyGroupRow, LegRow, PnLSparkline, ExpiryAlertPanel
│   └── ...              # events/, operations/, orders/, scanner/, ...
├── hooks/               # useEventsWS, useAlertsWS, usePositionalFeeds, useTradeMode, ...
├── lib/
│   ├── chartTheme.ts    # Shared recharts + lwc colour palette derived from CSS tokens
│   └── utils.ts         # cn() (clsx + tailwind-merge)
└── e2e/                 # Playwright test suite (shell-v2.spec.ts, ...)
```

## UI Kit (`components/ui/`)

All primitives are CVA-based and consume design tokens from `index.css @theme`. Edit freely — these are hand-rolled, not shadcn-generated.

| Component | Key props / notes |
|-----------|-------------------|
| `Button` | `variant`: primary/secondary/danger/ghost · `size`: sm/md/lg · `asChild` |
| `Card` + sub-components | CardHeader, CardTitle, CardContent, CardFooter |
| `Badge` | `variant`: default/success/warning/danger/info · `size`: sm/md |
| `DataTable<T>` | `data`, `columns` (ColumnDef[]), `searchable`, `pageSize`, `onRowClick`, `emptyMessage` |
| `Dialog` | Controlled via `open`/`onOpenChange` · ARIA `role="dialog"` + `aria-modal` · Escape key · focus trap |
| `Toast` / `useToast` | Imperative `toast({ variant, title, description })` · requires `<ToastProvider>` in root |
| `Skeleton` | `variant`: text/circular/rectangular |
| `Tabs` | TabsList, TabsTrigger, TabsContent |
| `Tooltip` | `content`, `placement`: top/right/bottom/left |

**`ToastProvider` is mounted in `__root.tsx`.** Do not add a second one.

## Chart Theme (`lib/chartTheme.ts`)

```ts
import { chartTheme } from '@/lib/chartTheme'
// use chartTheme.tooltip.bg / .border / .text for recharts contentStyle
// use chartTheme.colors.profit / .loss / .series[n] for data series
// rechartsDefaults() → ResponsiveContainer props
// lwcDefaults() → lightweight-charts ChartOptions
```

## Design Tokens (`index.css @theme`)

Key tokens: `--color-bullish`, `--color-bearish`, `--color-warning`, `--color-info`, `--color-primary`, `--color-surface`, `--color-text-main`, `--color-text-muted`, `--color-chart-*`, `--duration-fast/normal/slow`, `--ease-out`, `--breakpoint-sm/md/lg/xl`.

## Sidebar

Collapsible command-center sidebar with groups: TRADING / OPTIONS / DATA / SYSTEM. State persisted in `localStorage('sidebar_collapsed')`. Mobile: hamburger overlay at <768px. `ModeBanner` in footer. Unread event badge via `useUnreadEvents()`.

## Playwright e2e Verification

**Required after every frontend change.**

```bash
cd frontend && npx playwright test          # full suite
cd frontend && npx playwright test --grep "Backtest"  # single spec
```

Tests live in `frontend/e2e/`. Config: `playwright.config.ts` (auto-starts Vite dev server on :5173).

**Best practice for new routes:**
1. Add a `test.describe` block in `e2e/shell-v2.spec.ts` (or a new spec file).
2. Test: page header renders, key cards/sections visible, empty states graceful, error states show retry.
3. Use `domcontentloaded` not `networkidle` (avoids WS/polling timeouts).
4. Use `.or()` for elements that vary by backend state (data vs skeleton vs error card).
5. For API-dependent tests without a running backend: assert loading state (`.animate-pulse`) OR final state.

## API Integration

Backend base URL: `http://localhost:8000` (proxied by Vite in dev).

WebSocket endpoints:
- `ws://localhost:8000/ws/market` — tick stream
- `ws://localhost:8000/ws/portfolio` — MTM P&L  
- `ws://localhost:8000/ws/events` — live event feed
- `ws://localhost:8000/ws/jobs/{id}` — job progress

Use TanStack Query for REST. Always add `isError` / `refetch` handling — render an error card with a retry button, never a blank screen.
