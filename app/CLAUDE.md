# app/ — Flutter Trading App

Native UI for PDP. Dark, minimalist, 60fps on live data. **Android + Windows
desktop** from one Dart codebase. Replaces the removed React `frontend/`.

**Stack:** Flutter · Riverpod · go_router · web_socket_channel · dio · fl_chart ·
google_fonts (Inter).

## Non-negotiables

1. **Speed.** `const` widgets everywhere; `ListView.builder` (never a `Column` of
   N rows); narrow `ref.watch`/`select` so a tick rebuilds only what changed.
   Isolates for any heavy compute (none yet).
2. **Tokens once.** Colours, type, P&L styling come from `core/theme/` — never an
   inline `Color(...)` in a widget. Profit `#22C55E`, loss `#EF4444`, bg
   `#0F172A`, surface `#1E2937`.
3. **Feature shape.** Each feature is `features/<x>/{domain,data,application,
   presentation}`. Data goes behind a `Source` interface with **live + mock**
   impls selected by `AppConfig.useMock`; the screen consumes a Riverpod
   provider and never branches on data origin.
4. **Backend config via dart-define.** Never hardcode hosts. `AppConfig` reads
   `API_BASE` / `WS_BASE` / `USE_MOCK`. REST under `/api/v1`, WS under `/ws`.
5. **Verify after UI changes:** `flutter analyze && flutter test`.

## Backend contract (this slice)

- `GET /api/v1/portfolio/summary` → `{total_unrealized_pnl, total_realized_pnl,
  day_pnl, open_positions, mode}` (money may be strings).
- `GET /api/v1/portfolio/positions` → `{positions: [...], count}`.
- `WS /ws/portfolio` → `{type: "portfolio_update", positions: [...], summary: {...}}`;
  re-sends a full snapshot on connect. `summary.mode` drives the PAPER/LIVE badge.

## Key files

| Path | Role |
|------|------|
| `lib/main.dart` | `ProviderScope` + `MaterialApp.router` |
| `lib/core/network/ws_client.dart` | Reusable WS client, exp-backoff reconnect 1s→30s |
| `lib/core/config/app_config.dart` | Compile-time backend config |
| `lib/features/shell/app_shell.dart` | Responsive NavigationBar ↔ NavigationRail |
| `lib/features/portfolio/` | The live-portfolio vertical slice (reference pattern) |

## Not yet built

Order entry, option chain/analytics, backtest console, events/alerts, ML/ops —
each a future OpenSpec change cloning the portfolio pattern. `features/shell/
placeholder_screen.dart` lists them.
