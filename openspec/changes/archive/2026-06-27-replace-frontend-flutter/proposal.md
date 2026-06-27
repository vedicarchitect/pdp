## Why

The `frontend/` directory is a Vite + React 19 + TanStack SPA (13 routes, a hand-rolled
CVA UI kit, ~60 domain components, 19 hooks, Playwright + Cypress). It has grown into an
inconsistent, heavy, hard-to-evolve surface and the owner wants it gone. The goal is a
**modern, minimalist, blazing-fast** trading UI in the spirit of *Sahi Scalper*: a dark,
60fps experience tuned for live market data, on **mobile and desktop**, not just the
browser.

The Python FastAPI backend is unchanged and complete: **23 REST routers** under `/api/v1`
and **6 WebSocket hubs** under `/ws` (market, orders, portfolio, options, alerts, events)
plus `/ws/jobs/{id}`. The UI's job is to connect to that surface — "every dot, one by
one" — starting from a proven, end-to-end vertical slice rather than a big-bang rewrite.

A native Flutter app is the right tool: a single Dart codebase compiles to Android and
Windows with a real 60fps render pipeline, isolates for heavy compute, `const` widget
elision, and first-class `web_socket_channel` streaming — exactly the speed/quality bar
this project demands.

## What Changes

- **Remove** the entire React `frontend/` directory and retire its eight capability specs
  (`add-frontend-skeleton`, `frontend-ui-kit`, `frontend-shell`, `frontend-design-system`,
  `ui-animations`, `event-feed-ui`, `alerts-ui`, `order-entry-ui`).
- **Add** a new Flutter (Dart) application at `app/` targeting **Android + Windows desktop**,
  using **Riverpod** for state, **web_socket_channel** for live data, **fl_chart** for
  charts, and **google_fonts** (Inter) for type.
- Ship a **responsive app shell** (NavigationBar on compact widths, NavigationRail on wide)
  with a **dark design system** (backgrounds `#0F172A` / `#1E2937`, profit `#22C55E`, loss
  `#EF4444`) and large touch targets.
- Ship **one fully-wired vertical slice — the Live Portfolio screen** — as the canonical
  pattern: REST snapshot from `GET /api/v1/portfolio/summary` + `/positions`, live updates
  from `/ws/portfolio`, a P&L chart (fl_chart), and a PASS/LIVE mode badge.
- Provide a **realtime WS client** with exponential-backoff reconnect (1s → 30s) and a
  connection-status signal, plus a **configurable backend connection** (`--dart-define`
  for `API_BASE` / `WS_BASE`) so the same build points at localhost, a LAN host, or staging.
- Provide a **mock data source** (`--dart-define=USE_MOCK=true`) that simulates a live feed
  with zero backend, so the app runs, demos, and tests offline.

## Capabilities

### New Capabilities
- `trading-app`: a native Flutter trading client — scaffold, dark design system, responsive
  shell, realtime WS client with reconnect, configurable backend connection, a live
  portfolio screen, and an offline mock data simulation.

### Removed Capabilities
- `add-frontend-skeleton`, `frontend-ui-kit`, `frontend-shell`, `frontend-design-system`,
  `ui-animations`, `event-feed-ui`, `alerts-ui`, `order-entry-ui` — all React-era frontend
  capabilities, superseded by `trading-app`. The backend capabilities they consumed
  (`events`, `alerts`, `order-execution`, `portfolio`, `options-analytics`, …) are
  unaffected.

## Impact

- **Delete** `frontend/` (Vite app, `src/`, `e2e/`, `cypress/`, configs, `node_modules`).
- **New** `app/` Flutter project: `pubspec.yaml`, `analysis_options.yaml`, and `lib/`
  (`core/theme`, `core/config`, `core/network`, `core/router`, `shared/widgets`,
  `features/shell`, `features/portfolio`), plus a widget test and `app/CLAUDE.md`.
- **Docs**: root `CLAUDE.md` (drop the Playwright non-negotiable, swap the `frontend/`
  module row for `app/`), `openspec/project.md` (frontend tech-stack row → Flutter),
  `RUNBOOK.md` (replace `npm`/Playwright sections with Flutter run/test commands).
- **Specs**: delete the eight retired frontend spec folders under `openspec/specs/`.
  Archived changes under `openspec/changes/archive/` are left as historical record.
- **Backend**: no changes. Native targets need no CORS; the stubbed auth (`user_123`) is
  accepted as-is for this slice. CORS/auth become their own later changes if Flutter-web is
  ever targeted.
- **No new backend dependencies.** New Flutter dependencies are dev-tooling only and live in
  `app/pubspec.yaml`.
- **Out of scope** (each a later change reusing this slice's pattern): order entry, option
  chain/analytics, backtest warehouse console, events/alerts feeds, ML, operations.
