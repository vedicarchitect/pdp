## ADDED Requirements

### Requirement: Read-only Live Account (Dhan) surface

The system SHALL present the user's real, manually-taken Dhan account — equity/ETF holdings and
manual F&O/intraday positions — as a dedicated read-only surface distinct from the paper
strategy book. The surface SHALL have two tabs: Holdings (from
`GET /api/v1/broker-sync/holdings`) and Positions (manual F&O/intraday from
`GET /api/v1/broker-sync/positions`). The surface SHALL expose no order placement,
modification, or cancellation controls.

#### Scenario: Both Holdings and Positions are shown

- **WHEN** the Live Account surface is opened
- **THEN** it shows an equity/ETF Holdings tab and a manual F&O/intraday Positions tab, each
  read from the broker-sync mirror endpoints

#### Scenario: No order controls are present

- **WHEN** the Live Account surface is displayed
- **THEN** it exposes no buy/sell/modify/cancel controls — it is strictly read-only

### Requirement: Hard paper-vs-live account wall

The Live Account surface SHALL carry a `● LIVE (manual)` badge and every paper-strategy surface
(Dashboard, Execution, Journal) SHALL carry a `PAPER` badge, so the two account books are never
visually confused. Live Account figures SHALL NOT be blended into any paper Dashboard /
Execution / Journal P&L; the two books remain strictly separate.

#### Scenario: Live and paper surfaces are badged distinctly

- **WHEN** the user views the Live Account surface and any paper-strategy surface
- **THEN** the Live Account shows a `● LIVE (manual)` badge and the paper surfaces show a
  `PAPER` badge

#### Scenario: Live figures never enter paper P&L

- **WHEN** the paper Dashboard/Execution/Journal P&L is computed
- **THEN** it excludes all Live Account holdings/positions figures

### Requirement: Live-subscribed display MTM for manual positions

The manual positions' security ids (from the broker-sync PG mirror) SHALL be subscribed to the
live tick feed so the Positions tab shows real-time mark-to-market, strictly display-only — no
orders and no strategy ownership. The subscribed set SHALL be refreshed from the mirror on the
broker-sync EOD sync and on an on-demand `POST /api/v1/broker-sync/run` re-pull.

#### Scenario: Manual positions show live MTM

- **WHEN** the Positions tab is open and the market is live
- **THEN** each manual position's mark-to-market updates in real time from the same tick feed
  the strategy uses, without any order capability

#### Scenario: Subscription set refreshes on re-pull

- **WHEN** a broker-sync EOD sync or an on-demand `POST /api/v1/broker-sync/run` runs
- **THEN** the set of subscribed manual-position security ids is refreshed from the mirror
