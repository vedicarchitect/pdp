## 1. Design tokens and dependencies

- [x] 1.1 Check if `class-variance-authority` is in `frontend/package.json`; if not, add it: `cd frontend && npm install class-variance-authority`
- [x] 1.2 Check if `@tanstack/react-table` is in `frontend/package.json`; if not, add it: `cd frontend && npm install @tanstack/react-table`
- [x] 1.3 Add responsive breakpoint tokens to `frontend/src/index.css` under `@theme`: `--breakpoint-sm: 640px`, `--breakpoint-md: 768px`, `--breakpoint-lg: 1024px`, `--breakpoint-xl: 1280px`
- [x] 1.4 Add chart color tokens to `frontend/src/index.css`: `--color-chart-profit`, `--color-chart-loss`, `--color-chart-neutral`, `--color-chart-accent`, `--color-chart-series-*`
- [x] 1.5 Add animation/transition tokens to `frontend/src/index.css`: `--duration-fast: 150ms`, `--duration-normal: 250ms`, `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`
- [x] 1.6 Verify: `cd frontend && npm run build` — no errors

## 2. UI component library

- [x] 2.1 Create `frontend/src/components/ui/Button.tsx` — CVA variants: `primary`, `secondary`, `danger`, `ghost`; sizes: `sm`, `md`, `lg`; support `asChild` for link buttons
- [x] 2.2 Create `frontend/src/components/ui/Card.tsx` — `Card`, `CardHeader`, `CardTitle`, `CardContent`, `CardFooter` compound components
- [x] 2.3 Create `frontend/src/components/ui/Badge.tsx` — variants: `default`, `success`, `warning`, `danger`, `info`; sizes: `sm`, `md`
- [x] 2.4 Create `frontend/src/components/ui/Input.tsx` — text input with label, error state, helper text
- [x] 2.5 Create `frontend/src/components/ui/NumberField.tsx` — numeric input with min/max/step, formatted display
- [x] 2.6 Create `frontend/src/components/ui/Select.tsx` — dropdown select with options, label, error state
- [x] 2.7 Create `frontend/src/components/ui/Switch.tsx` — toggle switch with label
- [x] 2.8 Create `frontend/src/components/ui/Dialog.tsx` — modal dialog with overlay, title, description, close button; trap focus
- [x] 2.9 Create `frontend/src/components/ui/Tabs.tsx` — `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` compound components
- [x] 2.10 Create `frontend/src/components/ui/DataTable.tsx` — wraps `@tanstack/react-table`; props: `data`, `columns`, `searchable`, `pageSize`, `onRowClick`, `emptyMessage`; built-in sort indicators and pagination
- [x] 2.11 Create `frontend/src/components/ui/Toast.tsx` — toast notification with variants: `success`, `error`, `info`, `warning`; auto-dismiss timer; stack position bottom-right
- [x] 2.12 Create `frontend/src/components/ui/Skeleton.tsx` — animated loading placeholder; variants: `text`, `circular`, `rectangular`
- [x] 2.13 Create `frontend/src/components/ui/Tooltip.tsx` — hover tooltip with configurable placement
- [x] 2.14 Create `frontend/src/components/ui/index.ts` — barrel export of all components
- [x] 2.15 Verify: `cd frontend && npm run build` — no errors

## 3. Chart theme helper

- [x] 3.1 Create `frontend/src/lib/chartTheme.ts` — export `chartTheme` object with `colors` (profit/loss/neutral/accent/series array), `axis`, `tooltip`, `grid` configs
- [x] 3.2 Export `rechartsDefaults()` — function returning recharts `<ResponsiveContainer>` theme props
- [x] 3.3 Export `lwcDefaults()` — function returning lightweight-charts `ChartOptions` theme props
- [x] 3.4 Verify: `cd frontend && npx tsc --noEmit` — no type errors

## 4. Command-center sidebar

- [x] 4.1 Refactor `frontend/src/components/Sidebar.tsx` — add collapsible state (expanded/collapsed), persist in `localStorage`
- [x] 4.2 Group nav items into sections: TRADING (Dashboard, Intraday, Positional, Strategies), OPTIONS (Analytics, Builder), DATA (Portfolio, Instruments, Backtest), SYSTEM (Events, Alerts, Approvals, Operations)
- [x] 4.3 Add icon-only collapsed mode with `Tooltip` for labels
- [x] 4.4 Add mobile hamburger overlay for `<768px` breakpoint
- [x] 4.5 Add keyboard shortcut hint badges (e.g., `⌘1` for Dashboard)
- [x] 4.6 Integrate `ModeBanner` into sidebar footer (use `Badge` component)
- [x] 4.7 Verify: navigate all routes via sidebar — each link works, active state highlights correctly

## 5. Migrate existing pages to UI kit

- [x] 5.1 Refactor `frontend/src/components/intraday/*` — replace inline tables with `DataTable`, inline buttons with `Button`, card wrappers with `Card`
- [x] 5.2 Refactor `frontend/src/components/positional/*` — replace inline tables with `DataTable`, card wrappers with `Card`
- [x] 5.3 Refactor `frontend/src/components/analytics/*` — replace card wrappers with `Card`, apply `chartTheme` to all recharts instances
- [x] 5.4 Refactor `frontend/src/routes/strategies.tsx` — replace inline button/table markup with `Button`, `DataTable`, `Card`, `Badge`
- [x] 5.5 Refactor `frontend/src/components/ModeBanner.tsx` — use `Badge` variants for PAPER/LIVE/SEMI-AUTO labels
- [x] 5.6 Verify: `cd frontend && npm run build` — no errors
- [x] 5.7 Visual check: open each page in browser, compare before/after for visual regressions

## 6. Wire stub routes

- [x] 6.1 Update `frontend/src/routes/portfolio.tsx` — fetch `GET /api/v1/portfolio/holdings` and `GET /api/v1/portfolio/positions`; render in two `Card` + `DataTable` sections with summary stats at top
- [x] 6.2 Update `frontend/src/routes/instruments.tsx` — fetch `GET /api/v1/instruments`; render in searchable `DataTable` with exchange segment `Badge` filters
- [x] 6.3 Update `frontend/src/routes/backtest.tsx` — render "coming soon" skeleton with a description of upcoming backtester capabilities; link to proposal `2026-06-17-options-strategy-backtester`
- [x] 6.4 Verify: navigate to `/portfolio`, `/instruments`, `/backtest` — each renders with real data (or skeleton)
- [x] 6.5 Verify: `cd frontend && npm run build` — clean build

## 7. Final verification

- [x] 7.1 Run `cd frontend && npm run build` — clean production build
- [x] 7.2 Run `cd frontend && npx tsc --noEmit` — no type errors
- [x] 7.3 Run `cd frontend && npm run lint` — no lint errors (pre-existing lint issues in other files; no new issues introduced)
- [x] 7.4 Visual walkthrough: check Dashboard, Intraday, Positional, Strategies, Analytics, Portfolio, Instruments, Backtest — all render correctly with consistent styling
- [x] 7.5 Test responsive: resize browser to 768px (tablet) and 375px (mobile) — layout adapts, sidebar collapses/hamburger works
