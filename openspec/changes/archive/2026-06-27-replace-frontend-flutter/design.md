# Design — replace-frontend-flutter

## Goals & constraints

- **60fps on live data.** `const` widgets, `ListView.builder`, narrow `ref.watch` so a tick
  rebuilds only the rows that changed, isolates reserved for any future heavy compute.
- **Native first.** Android + Windows desktop from one codebase; web is explicitly out of
  scope (so no CORS work on the backend).
- **Minimal surface now, proven pattern.** Ship the shell + one real screen (live portfolio)
  wired end-to-end; every later screen clones this data → provider → presentation shape.
- **Backend untouched.** Consume the existing `/api/v1` + `/ws` surface as-is.

## Layered architecture (`app/lib/`)

```
main.dart                    ProviderScope → TradingApp (MaterialApp.router, dark theme)
core/
  theme/app_colors.dart      raw tokens (#0F172A, #1E2937, #22C55E, #EF4444, text greys)
  theme/app_theme.dart       ThemeData.dark() + GoogleFonts.interTextTheme; 48dp targets
  config/app_config.dart     API_BASE / WS_BASE / USE_MOCK from String.fromEnvironment
  network/api_client.dart    dio instance bound to AppConfig.apiBase
  network/ws_client.dart     web_socket_channel wrapper: broadcast Stream + backoff reconnect
  router/app_router.dart     GoRouter with a ShellRoute → AppShell
shared/widgets/
  pnl_text.dart              AnimatedDefaultTextStyle, green/red by sign, mono digits
  stat_card.dart             labelled metric card
  connection_badge.dart      consumes connectionStatusProvider
  mode_badge.dart            PAPER (amber) / LIVE (red)
features/
  shell/app_shell.dart       LayoutBuilder → NavigationBar (compact) | NavigationRail (wide)
  portfolio/
    domain/position.dart            immutable model + fromJson
    domain/portfolio_summary.dart   immutable model + fromJson
    domain/portfolio_snapshot.dart  {summary, positions, status}
    data/portfolio_source.dart      abstract PortfolioSource { Stream<PortfolioSnapshot> watch() }
    data/live_portfolio_source.dart REST seed (api_client) + /ws/portfolio (ws_client)
    data/mock_portfolio_source.dart Stream.periodic randomized P&L
    application/portfolio_providers.dart  sourceProvider (mock|live) + portfolioProvider (StreamProvider)
    presentation/portfolio_screen.dart    summary card + ListView.builder + PnlChart
    presentation/pnl_chart.dart           fl_chart LineChart of day-P&L history
```

## Riverpod graph

- `appConfigProvider` → `AppConfig` (compile-time constants).
- `connectionStatusProvider` (`StateProvider<ConnStatus>`) → driven by `ws_client`, read by
  `ConnectionBadge`.
- `portfolioSourceProvider` → returns `MockPortfolioSource` when `AppConfig.useMock` else
  `LivePortfolioSource` (constructed with `api_client` + `ws_client`). Same `PortfolioSource`
  interface, so the screen never branches on data origin.
- `portfolioProvider` (`StreamProvider<PortfolioSnapshot>`) → `source.watch()`. The screen
  `ref.watch`es it; rows select their own position by id to avoid whole-list rebuilds.

## Live data flow (portfolio)

1. `LivePortfolioSource.watch()` first `GET /api/v1/portfolio/summary` + `/positions` (dio),
   yields a seed `PortfolioSnapshot`.
2. Opens `ws_client` on `${WS_BASE}/ws/portfolio`; the backend pushes an initial
   `portfolio_update` then deltas. Each message → decode `{positions, summary}` → yield a new
   snapshot. (Backend contract confirmed in `src/pdp/portfolio/ws.py` /`routes.py`.)
3. `ws_client` owns reconnection: exponential backoff 1→2→4→8…→30s, updating
   `connectionStatusProvider`. On reconnect the backend re-sends its snapshot, so no gap
   handling is needed in the source.
4. `mode` comes from `summary.mode` (`paper`|`live`) → `ModeBadge`. No header parsing needed.

## Mock simulation

`MockPortfolioSource` seeds a handful of fictional NIFTY/BANKNIFTY option positions and uses
`Stream.periodic(~500ms)` to jitter each position's unrealized P&L (bounded random walk),
recomputing the summary. Selected purely by `AppConfig.useMock`, it lets the app run, demo,
and be widget-tested with no backend and no flakiness.

## Theming & motion

- One `ThemeData.dark()` built from `app_colors.dart`; `GoogleFonts.interTextTheme` for type;
  card/elevation/shape tuned for a flat, minimal look.
- Motion is restrained: `AnimatedDefaultTextStyle`/implicit animations only on values that
  change (P&L numbers, badge colour). No route-transition flourishes.

## Performance notes

- `const` constructors throughout; `ListView.builder` (never a `Column` of N rows).
- Provider selectors (`ref.watch(portfolioProvider.select(...))`) keep per-row rebuilds local.
- Isolates: not needed for this slice (no heavy compute); documented as the path for future
  analytics/backtest math.

## Configuration & runbook

- `flutter run -d windows --dart-define=USE_MOCK=true` — offline demo.
- `flutter run -d windows --dart-define=API_BASE=http://localhost:8000 --dart-define=WS_BASE=ws://localhost:8000`
  — live against `task dev`.
- Android device on the same LAN: `--dart-define=API_BASE=http://<host-ip>:8000` (+ matching
  `WS_BASE`); the backend binds all interfaces, no CORS needed for native.

## Decisions & alternatives

- **Riverpod over Bloc** — less boilerplate for this provider-graph style; the user listed
  Riverpod first. Bloc remains viable but is not used.
- **fl_chart over syncfusion** — MIT-licensed, lightweight, sufficient for line/sparkline P&L;
  avoids Syncfusion's license. Revisit only if candlestick+indicator overlays are needed.
- **dio over http** — interceptors/timeouts/typed errors out of the box for the REST layer.
- **No code-gen (freezed/json_serializable) in this slice** — hand-written immutable models
  keep the first cut dependency-light and analyzer-clean; can be introduced later if model
  count grows.
