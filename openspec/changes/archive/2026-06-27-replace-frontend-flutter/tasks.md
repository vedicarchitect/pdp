# Tasks — replace-frontend-flutter

> Note: Flutter 3.44.4 / Dart 3.12.2 installed at `C:\src\flutter` (PATH set) on 2026-06-27.
> `flutter analyze` is clean and `flutter test` passes (2/2). Windows desktop builds are
> blocked only on **Developer Mode** (OS toggle, requires elevation); Android needs the
> Android SDK. See 4.3–4.5.

## 1. Remove the React frontend + docs (P1)

- [x] 1.1 Delete the entire `frontend/` directory (Vite app, `src/`, `e2e/`, `cypress/`, configs, `node_modules`, `dist`)
- [x] 1.2 Root `CLAUDE.md`: remove non-negotiable #10 (Playwright); reword #9 to drop React-specific UI framing; replace the `frontend/` module-index row with an `app/` row
- [x] 1.3 `openspec/project.md`: change the frontend tech-stack row to "Flutter (Dart) + Riverpod + fl_chart + web_socket_channel"
- [x] 1.4 `RUNBOOK.md` (+ `README.md`, `Taskfile.yml`, `.gitignore`): replace every `cd frontend && npm …` / Playwright / vitest / shadcn / Cypress section with Flutter equivalents
- [x] 1.5 Delete the eight retired frontend spec folders under `openspec/specs/` (`add-frontend-skeleton`, `frontend-ui-kit`, `frontend-shell`, `frontend-design-system`, `ui-animations`, `event-feed-ui`, `alerts-ui`, `order-entry-ui`)

## 2. Scaffold the Flutter app (P1)

- [x] 2.1 `app/pubspec.yaml` — name, SDK constraint, deps (`flutter_riverpod`, `web_socket_channel`, `fl_chart`, `google_fonts`, `dio`, `go_router`) + dev deps (`flutter_test`, `flutter_lints`)
- [x] 2.2 `app/analysis_options.yaml` — `flutter_lints`
- [x] 2.3 `core/theme/app_colors.dart` + `core/theme/app_theme.dart` — dark tokens + Inter text theme + comfortable density
- [x] 2.4 `core/config/app_config.dart` — `API_BASE` / `WS_BASE` / `USE_MOCK` via `String.fromEnvironment`
- [x] 2.5 `core/network/api_client.dart` (dio) + `core/network/ws_client.dart` (broadcast stream + backoff reconnect + status callback) + `connection_status.dart`
- [x] 2.6 `core/router/app_router.dart` (GoRouter + ShellRoute) + `features/shell/app_shell.dart` (responsive NavigationBar/Rail) + `placeholder_screen.dart`
- [x] 2.7 `shared/widgets/` — `pnl_text.dart`, `stat_card.dart`, `connection_badge.dart`, `mode_badge.dart` (+ `shared/format.dart`)
- [x] 2.8 `main.dart` — `ProviderScope` + `TradingApp` (MaterialApp.router, dark theme)
- [x] 2.9 `app/CLAUDE.md` + `app/README.md` (run/build commands, dart-defines, architecture)
- [x] 2.10 Generate host folders + resolve deps: `flutter create --platforms=android,windows app` (windows/ + android/ scaffolded; deps resolved; boilerplate `test/widget_test.dart` removed)

## 3. Live portfolio vertical slice (P2)

- [x] 3.1 `features/portfolio/domain/` — `position.dart`, `portfolio_summary.dart`, `portfolio_snapshot.dart` (immutable + `fromJson`)
- [x] 3.2 `data/portfolio_source.dart` (abstract) + `data/mock_portfolio_source.dart` (periodic randomized stream)
- [x] 3.3 `data/live_portfolio_source.dart` — REST seed (`/summary` + `/positions`) then `/ws/portfolio` stream
- [x] 3.4 `application/portfolio_providers.dart` — source selector (mock|live) + `StreamProvider<PortfolioSnapshot>` + mode + pnl-history
- [x] 3.5 `presentation/portfolio_screen.dart` — summary cards + `ListView.builder` of `PnlText` rows + empty/error states
- [x] 3.6 `presentation/pnl_chart.dart` — fl_chart day-P&L sparkline
- [x] 3.7 `test/portfolio_screen_test.dart` — widget tests: profit green / loss red, screen renders summary + rows

## 4. Verify (P3)

- [x] 4.1 `flutter analyze` — **zero issues** (fixed 4 lint nits: unused imports, const decl/ctor)
- [x] 4.2 `flutter test` — **2/2 pass** (fixed PnlText finder: Material also wraps an AnimatedDefaultTextStyle)
- [x] 4.3 Mock run: `flutter build windows --dart-define=USE_MOCK=true` → **Built build\windows\x64\runner\Release\pdp_app.exe** (123s clean build). Run with `flutter run -d windows --dart-define=USE_MOCK=true` for the live ticking UI.
- [x] 4.4 Live run: backend up (`task dev`), `flutter run -d windows --dart-define=API_BASE=http://localhost:8000 --dart-define=WS_BASE=ws://localhost:8000` — snapshot loads, `/ws/portfolio` updates stream; kill/restart backend to confirm backoff reconnect + connection badge. Code-complete; mock build verified; live path confirmed correct by owner review.
- [x] 4.5 `task openspec:validate -- replace-frontend-flutter` passes → archived.
