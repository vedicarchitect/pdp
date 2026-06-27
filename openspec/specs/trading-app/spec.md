# trading-app Specification

## Purpose
TBD - created by archiving change replace-frontend-flutter. Update Purpose after archive.
## Requirements
### Requirement: Flutter application scaffold
The system SHALL provide a Flutter (Dart) application under `app/` that builds for
**Android** and **Windows desktop** from a single codebase, with dependencies on
`flutter_riverpod`, `web_socket_channel`, `fl_chart`, `google_fonts`, `dio`, and `go_router`
declared in `app/pubspec.yaml`, and a clean static analysis (`flutter analyze` reports no
errors against `app/analysis_options.yaml`).

#### Scenario: Project analyzes clean
- **WHEN** `flutter pub get` then `flutter analyze` is run inside `app/`
- **THEN** dependencies resolve and analysis completes with zero errors

#### Scenario: Builds for both targets
- **WHEN** the app is launched with `flutter run -d windows` or `flutter run -d <android>`
- **THEN** the app starts and renders the shell without runtime exceptions

### Requirement: Dark design system
The system SHALL apply a dark Material theme whose tokens are defined once in
`app/lib/core/theme/` and consumed everywhere: background `#0F172A`, surface `#1E2937`,
profit/positive `#22C55E`, loss/negative `#EF4444`, with the Inter typeface via
`google_fonts`. Profit-and-loss values SHALL render green when ≥ 0 and red when < 0 via a
shared widget, and interactive targets SHALL be at least 48dp.

#### Scenario: Tokens are centralized
- **WHEN** any screen needs a colour, font, or P&L style
- **THEN** it reads it from the shared theme/token source, not an inline literal

#### Scenario: P&L colour reflects sign
- **WHEN** a P&L value is positive it renders in `#22C55E`, and when negative in `#EF4444`

### Requirement: Responsive app shell and navigation
The system SHALL provide an app shell that adapts to viewport width: a bottom
`NavigationBar` on compact widths (phones) and a side `NavigationRail` on wide widths
(desktop/tablet), driven by a single breakpoint. The shell SHALL host the routed screens via
`go_router` and SHALL display a connection-status indicator and the PAPER/LIVE mode badge.

#### Scenario: Compact layout uses a bottom bar
- **WHEN** the window is narrower than the breakpoint
- **THEN** navigation is presented as a bottom `NavigationBar`

#### Scenario: Wide layout uses a rail
- **WHEN** the window is wider than the breakpoint
- **THEN** navigation is presented as a side `NavigationRail`

### Requirement: Realtime WebSocket client with backoff reconnect
The system SHALL provide a reusable WebSocket client (`app/lib/core/network/ws_client.dart`)
built on `web_socket_channel` that exposes the inbound messages as a broadcast `Stream`,
reconnects automatically with exponential backoff (1s → 2s → 4s → 8s, capped at 30s) when the
socket closes unexpectedly, and publishes a connection state
(`connecting | connected | reconnecting | disconnected`) observable via Riverpod.

#### Scenario: Reconnects after an unexpected close
- **WHEN** the underlying socket closes unexpectedly
- **THEN** the client retries with increasing delay capped at 30s and surfaces a
  `reconnecting` state until it re-establishes the connection

#### Scenario: Connection state is observable
- **WHEN** the socket transitions between connecting, connected, and disconnected
- **THEN** the connection-status provider emits the new state and the shell badge updates

### Requirement: Configurable backend connection
The system SHALL resolve the backend REST base URL and WebSocket base URL from compile-time
configuration (`app/lib/core/config/app_config.dart`) overridable via
`--dart-define=API_BASE=...` and `--dart-define=WS_BASE=...`, defaulting to
`http://localhost:8000` and `ws://localhost:8000`. REST calls SHALL target paths under
`/api/v1` and WebSocket connections SHALL target paths under `/ws`.

#### Scenario: Defaults to localhost
- **WHEN** the app is launched without backend dart-defines
- **THEN** it targets `http://localhost:8000` for REST and `ws://localhost:8000` for WS

#### Scenario: Overridable for a LAN host
- **WHEN** launched with `--dart-define=API_BASE=http://192.168.1.10:8000`
- **THEN** REST and WS calls target that host without code changes

### Requirement: Mock data simulation for offline development
The system SHALL provide a mock data source selected by `--dart-define=USE_MOCK=true` that
emits a simulated live portfolio stream (periodic randomized P&L updates) without contacting
any backend, so the app runs, demos, and is testable offline. The live and mock sources SHALL
satisfy the same interface so screens are agnostic to which is active.

#### Scenario: Runs with zero backend
- **WHEN** the app is launched with `--dart-define=USE_MOCK=true` and no backend is running
- **THEN** the live portfolio screen renders and updates from the simulated stream

#### Scenario: Live and mock are interchangeable
- **WHEN** the data source is switched between live and mock
- **THEN** the portfolio screen consumes the same provider interface unchanged

### Requirement: Live portfolio screen
The system SHALL provide a live portfolio screen that loads an initial snapshot from
`GET /api/v1/portfolio/summary` and `GET /api/v1/portfolio/positions`, then applies live
updates from `/ws/portfolio` (`portfolio_update` messages carrying `positions` and
`summary`). It SHALL render a header summary card (total unrealized, total realized, day P&L,
open positions, and the mode badge), a scrollable positions list built with
`ListView.builder`, and a P&L chart rendered with `fl_chart`. Numeric changes SHALL animate
subtly; the list SHALL not rebuild wholesale on each tick.

#### Scenario: Snapshot then live updates
- **WHEN** the screen opens against a running backend
- **THEN** it shows the REST snapshot and thereafter updates totals and positions from the
  `/ws/portfolio` stream

#### Scenario: Empty state
- **WHEN** there are no open positions
- **THEN** the list shows an empty-state message and the summary card shows zeroed P&L

#### Scenario: Mode badge reflects backend
- **WHEN** the portfolio summary reports `mode: "paper"`
- **THEN** a PAPER badge is shown; when `mode: "live"`, a LIVE badge is shown

