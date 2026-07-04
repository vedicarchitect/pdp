## Context

The current `app/lib/features/backtest/**` scaffold calls `ApiClient` directly (no `Source`/mock
split, violating `app/CLAUDE.md`), renders only a `cumEquity` line and a raw-JSON config box, and has
no days/trades/folds/coverage/comparison/decision views. `app/CLAUDE.md` mandates: feature =
`domain/data/application/presentation`, data behind a `Source` interface with live+mock impls chosen
by `AppConfig.useMock`, colors/P&L from `core/theme/`, and `flutter analyze && flutter test`
verification. Backend APIs come from changes 1–4: `/strangle-backtests/*` (runs/days/folds/trades,
sweeps leaderboard, decisions, promotion rationale, vs-paper), `/coverage`, `/strategies`, and
`/ws/jobs` progress.

## Goals / Non-Goals

**Goals:**
- Rebuild the feature to house convention (Source+mock, theme tokens, feature layering).
- Deliver the console, run-detail drill-downs, launch flow, coverage/gap-radar panel, promotion and
  paper-comparison views, and export — at 60fps on live data.
- Replace the raw-JSON config box with a registry-driven strategy/param picker.
- Cover with Flutter widget/integration tests.

**Non-Goals:**
- Backend changes — this change only consumes the change 1–4 APIs.
- New charting dependencies beyond the existing `fl_chart`.

## Decisions

### 1. `BacktestSource` interface + live/mock impls
Introduce `BacktestSource` in `data/` with `BacktestLiveSource` (dio/`ApiClient`) and
`BacktestMockSource` (fixtures), selected by `AppConfig.useMock` via a Riverpod provider. Rationale:
house rule #3; enables UI dev + tests without a backend. Replaces the direct-`ApiClient`
`BacktestRepository`.

### 2. Screen structure
- Console screen: runs table (filter/sort/verdict/promotion chips) + index selector + sweep
  leaderboard tab.
- Run-detail screen: equity+drawdown chart, day table, trade drill-down, decision-trace panel
  (events by default, "load full minute trace" action), walk-forward folds panel.
- Launch dialog: strategy picker (`/strategies`) → editable param form (schema-driven) → window +
  index → kind (single/sweep/walkforward) → launch with `/ws/jobs` progress.
- Coverage panel: `/coverage` grid with per-gap backfill buttons (job progress).
- Promotion dialog: rationale/evidence + optional note.
- Paper-comparison view: overlay + per-day divergence, expand a date to minute-level diff.
Rationale: mirrors the backend capability boundaries so each screen maps to one API area.

### 3. Charts reuse `fl_chart`
Equity+drawdown as dual series; leaderboard as a table; no new deps. Rationale: consistency + bundle
size.

### 4. Export on desktop
CSV/JSON export writes to disk via the desktop file APIs already used by the app. Rationale: the app
targets Windows desktop; keep export native.

### 5. Tests
Widget tests drive each screen off `BacktestMockSource`; an integration test covers the launch→job→
appears-in-table flow with a fake job stream. Rationale: house verification is `flutter analyze &&
flutter test`; the mock source makes screens deterministic.

## Risks / Trade-offs

- [API surface still firming as changes 1–4 land] → code against the mock source first; keep the
  live source thin and typed so endpoint shape changes are localized.
- [Decision trace / minute diff can be large] → default to events; load the full per-minute trace and
  minute-diff only on explicit user action (matches backend on-demand model).
- [60fps on large tables] → paginate/virtualize the runs and day tables; charts render summarized
  series.
- [Scaffold rewrite churn] → replace `BacktestRepository` with the Source split in one pass; keep the
  existing routes (`/backtests`, `/backtests/:id`) stable.

## Migration Plan

1. Introduce `BacktestSource` (+ live/mock) and migrate existing screens off `BacktestRepository`.
2. Build the console (table + leaderboard + index selector) and run-detail (equity+drawdown, days,
   trades, folds, decision trace).
3. Build the launch flow against `/strategies` (registry picker + param form).
4. Add the coverage/gap-radar panel and the promotion + paper-comparison views.
5. Add export + dashboard links.
6. Add widget/integration tests; run `flutter analyze && flutter test`.
Rollback: it's an additive UI rebuild behind existing routes; the mock source keeps it runnable even
if a backend endpoint lags.

## Open Questions

- Should the coverage/gap-radar live inside the backtest console or as its own top-level screen linked
  from it? Leaning a panel within the console launch flow (you check data before running), with a
  deep link from the dashboard.
