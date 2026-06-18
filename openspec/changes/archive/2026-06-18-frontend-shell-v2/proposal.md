## Why

PDP's frontend has no shared component layer — buttons, tables, modals, and form inputs are copy-pasted per page with inconsistent styling. Three route stubs (`/portfolio`, `/backtest`, `/instruments`) render empty shells. Charts use inconsistent color palettes across pages, and the layout is not responsive. Before any feature proposal (strategy builder, backtester, analytics, virtual trading) can land cleanly, the frontend needs a unified component library, a command-center navigation shell, and functional skeleton pages for the three stub routes.

Rivals like Sahi ship a single-screen command center that packs option chain, payoff, OI/PCR, and positions into one view with zero page navigation. Sensibull uses a consistent design system across builder, chain, and virtual trading. PDP's current page-by-page layout with per-page ad-hoc components cannot match this without a foundational refactor first.

## What Changes

- **New `frontend/src/components/ui/` library**: Reusable primitives built on Class Variance Authority (CVA) and existing Tailwind v4 `@theme` design tokens — `Button`, `DataTable` (sort/filter/pagination), `Dialog` (modal), `Tabs`, `Card`, form inputs (`Select`, `Input`, `NumberField`, `Switch`), `Toast` (notification), `Badge`, `Skeleton` (loading placeholder), and `Tooltip`.
- **Refactor existing components**: `KillSwitchButton`, `RolloverPanel`, position/journal tables, and analytics panels migrate onto the new UI kit — removing inline/duplicate styling.
- **Command-center shell**: Reworked `Sidebar.tsx` with collapsible nav groups, icon-only collapsed mode, keyboard shortcut hints, and a mobile hamburger breakpoint. Inspired by Sahi's dense, single-screen layout.
- **Responsive breakpoints**: Tailwind v4 `@theme` screen tokens (`sm`, `md`, `lg`, `xl`) with a mobile-first grid system.
- **Chart theme helper**: `frontend/src/lib/chartTheme.ts` — shared color palette, axis styling, and tooltip format for recharts and lightweight-charts, derived from design tokens.
- **Wire stub routes**: `/portfolio` → real skeleton using existing `GET /api/v1/portfolio/*` endpoints; `/instruments` → instrument browser using `GET /api/v1/instruments`; `/backtest` → placeholder with "coming soon" that links to proposal `2026-06-17-options-strategy-backtester`.
- **No backend changes.**

## Capabilities

### New Capabilities
- `frontend-ui-kit`: Shared component library (`components/ui/`) with CVA-based primitives, consistent with Tailwind v4 design tokens.

### Modified Capabilities
- `frontend-design-system`: Add responsive breakpoint tokens, chart color palette tokens, and animation/transition tokens to `index.css`.
- `frontend-shell`: Rework sidebar into a collapsible command-center navigation with icon-only mode, mobile breakpoint, and keyboard shortcut hints.
- `portfolio`: Wire `/portfolio` route to display holdings and positions from existing API endpoints.

## Impact

- `frontend/src/components/ui/Button.tsx` — NEW
- `frontend/src/components/ui/DataTable.tsx` — NEW
- `frontend/src/components/ui/Dialog.tsx` — NEW
- `frontend/src/components/ui/Tabs.tsx` — NEW
- `frontend/src/components/ui/Card.tsx` — NEW
- `frontend/src/components/ui/Select.tsx` — NEW
- `frontend/src/components/ui/Input.tsx` — NEW
- `frontend/src/components/ui/NumberField.tsx` — NEW
- `frontend/src/components/ui/Switch.tsx` — NEW
- `frontend/src/components/ui/Toast.tsx` — NEW
- `frontend/src/components/ui/Badge.tsx` — NEW
- `frontend/src/components/ui/Skeleton.tsx` — NEW
- `frontend/src/components/ui/Tooltip.tsx` — NEW
- `frontend/src/components/ui/index.ts` — NEW (barrel export)
- `frontend/src/lib/chartTheme.ts` — NEW
- `frontend/src/index.css` — MODIFIED (add responsive, chart, animation tokens)
- `frontend/src/components/Sidebar.tsx` — MODIFIED (command-center refactor)
- `frontend/src/components/ModeBanner.tsx` — MODIFIED (use Badge from ui-kit)
- `frontend/src/components/intraday/*` — MODIFIED (migrate to DataTable, Button, Card)
- `frontend/src/components/positional/*` — MODIFIED (migrate to DataTable, Card)
- `frontend/src/components/analytics/*` — MODIFIED (use Card, chartTheme)
- `frontend/src/routes/portfolio.tsx` — MODIFIED (wire to API)
- `frontend/src/routes/instruments.tsx` — MODIFIED (wire to API)
- `frontend/src/routes/backtest.tsx` — MODIFIED (coming-soon skeleton)
- `frontend/src/routes/__root.tsx` — MODIFIED (if route registration needs update)
- No new external npm dependencies (CVA may already be in use; if not, add `class-variance-authority`).
- No backend changes.
