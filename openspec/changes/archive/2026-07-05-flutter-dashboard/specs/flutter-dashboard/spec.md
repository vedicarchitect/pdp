## ADDED Requirements

### Requirement: House-convention feature architecture
The dashboard feature SHALL follow the app's house convention: `domain/data/application/
presentation` layering with a `DashboardSource` interface backed by both a live implementation and a
mock implementation selected via `AppConfig.useMock`, and all colors/P&L styling SHALL come from
`core/theme/` (no inline `Color(...)`).

#### Scenario: Mock source drives the UI without a backend
- **WHEN** the app runs with `AppConfig.useMock` enabled
- **THEN** the dashboard renders every section from the mock `DashboardSource` without any network calls

#### Scenario: P&L styling comes from the theme
- **WHEN** profit and loss values are displayed on the dashboard
- **THEN** their colors come from `core/theme/` tokens, not inline color literals

### Requirement: Single-call aggregation with live deltas over existing sockets
The dashboard SHALL seed its initial state from one `GET /api/v1/dashboard` call and SHALL apply
live updates via the existing `/ws/market` (index/commodity ticks) and `/ws/portfolio` (P&L,
positions) sockets — no additional WebSocket connection SHALL be opened for this feature.

#### Scenario: Dashboard seeds from a single call
- **WHEN** the dashboard screen first loads
- **THEN** exactly one REST call to `/api/v1/dashboard` populates every section before any WS message arrives

#### Scenario: Live ticks update index cards without a re-fetch
- **WHEN** a `/ws/market` tick arrives for a subscribed index or commodity security id
- **THEN** the corresponding card's LTP and change updates in place without calling `/api/v1/dashboard` again

### Requirement: Correct index/commodity change math
The dashboard SHALL display `change` and `change_pct` computed against the previous session's close
(`prev_close`), not a running intraday sum. The client SHALL seed `prev_close` from the initial
aggregation response and recompute `change`/`change_pct` from each subsequent tick's `ltp` against
that same `prev_close`.

#### Scenario: Change reflects vs-prev-close, not running sum
- **WHEN** an index's `prev_close` is 100 and a tick arrives with `ltp` 102
- **THEN** the displayed change is `+2` (`+2.0%`), independent of how many prior ticks were received that session

### Requirement: Per-section honest degradation
Each dashboard section SHALL independently reflect its own `available` flag from the backend
(global indices, commodities, VIX, FII/DII, sentiment/news, next-expiry). A section with
`available: false` SHALL render as hidden or visibly unavailable (e.g. greyed placeholder) — it
SHALL NEVER display a fabricated or last-known-good value silently as if it were current.

#### Scenario: An unavailable section is visibly absent
- **WHEN** `/api/v1/dashboard` reports `fii_dii.available: false`
- **THEN** the FII/DII panel is hidden or shown as unavailable, not populated with placeholder numbers

#### Scenario: An available section shows its as_of freshness
- **WHEN** a section reports `available: true` with an `as_of` timestamp
- **THEN** the section renders its data and the `as_of` age is available to the UI (e.g. for a "stale" indicator)

### Requirement: Dashboard sections and layout
The dashboard SHALL be the app's canonical home screen showing: index cards (NIFTY/BANKNIFTY/SENSEX
spot, change, trend) with a sparkline, a global-markets strip (Dow/Nasdaq/S&P/Nikkei/Hang Seng/FTSE),
a commodities strip (MCX gold/crude/natgas/silver in INR), an India VIX gauge, portfolio snapshot
tiles (paper+live positions, live P&L, today's realized P&L, margin utilized/available),
strategy-status chips, an FII/DII panel (yesterday + last 7 days), a blended sentiment gauge with its
news feed, upcoming expiry chips per index, and a user-editable watchlist.

#### Scenario: All sections render from real or honestly-degraded data
- **WHEN** the dashboard is loaded against the live backend
- **THEN** every section shows real values from its backing source, or is marked/hidden as unavailable — no section ever shows a hardcoded placeholder value

### Requirement: User-editable watchlist
The dashboard SHALL let the user add/remove symbols to a personal watchlist, persisted locally on
the device (no backend watchlist capability exists in this change), and SHALL resolve live quotes
for watchlist symbols from the same index/LTP data path used elsewhere on the dashboard.

#### Scenario: A symbol is added to the watchlist and persists across restarts
- **WHEN** the user adds a symbol to the watchlist and restarts the app
- **THEN** the symbol remains in the watchlist and its live quote is shown

### Requirement: Dashboard covered by Flutter tests
The dashboard's screen and widgets SHALL be covered by Flutter widget tests (not Playwright),
runnable via `flutter analyze && flutter test`.

#### Scenario: Dashboard tests run in the Flutter toolchain
- **WHEN** `flutter analyze && flutter test` is run
- **THEN** the dashboard's widget tests execute and pass using the mock `DashboardSource`
