# strangle-live-dte-window Specification

## Purpose

The directional strangle strategy should enter only in the last N days before expiry — where theta
decay is steepest and the bias edge is strongest — rather than opening new legs early in the expiry
cycle. The `dte_max` config field already exists and is honoured by the backtest via the shared
`within_dte(trade_date, expiry, dte_max)` calendar helper, but the live `DirectionalStrangle`
strategy never reads it, so live/paper trading opens legs regardless of days-to-expiry. This
capability wires the existing `dte_max` field into the live entry gate — reusing the same helper the
backtest uses — so live and backtest apply the identical DTE filter, with no new config concept and
no hardcoded expiry weekday.

## Requirements

### Requirement: Live strangle SHALL gate new entries by days-to-expiry

The live `DirectionalStrangle` strategy SHALL read the existing `dte_max` config field and SHALL
open new legs only when the current trade day is within `dte_max` calendar days of the resolved
expiry, using the same `within_dte(trade_date, expiry, dte_max)` calculation as the backtest. When
`dte_max` is `null`/absent the behaviour is unchanged (no DTE filter). The gate SHALL block new
entries only — existing open legs continue to be managed and squared off normally. Expiry SHALL be
resolved dynamically (never a hardcoded weekday).

#### Scenario: New entry blocked outside the DTE window

- **WHEN** `dte_max` is 15 and the current day is 20 calendar days before the resolved expiry
- **THEN** the strategy opens no new legs and records a `dte_gated` reason on the bias/heartbeat event

#### Scenario: New entry allowed inside the DTE window

- **WHEN** `dte_max` is 15 and the current day is 8 calendar days before the resolved expiry
- **THEN** the strategy evaluates bias and may open legs as normal

#### Scenario: Existing legs are managed regardless of the DTE gate

- **WHEN** the DTE gate is blocking new entries but open legs exist
- **THEN** those legs are still stop-managed, rolled, and squared off, and only *new* entries are suppressed

#### Scenario: Null dte_max preserves current behaviour

- **WHEN** `dte_max` is `null` or absent
- **THEN** the strategy applies no DTE filter and behaves exactly as before

### Requirement: Live and backtest SHALL apply the identical DTE filter

The live DTE gate SHALL reuse the shared `instruments/expiry_calendar.within_dte` helper so that a
live day and a backtest of the same window and `dte_max` make the same enter/skip decision, with no
divergent DTE logic.

#### Scenario: Same decision live and backtest

- **WHEN** the same `dte_max` and expiry apply on a given day
- **THEN** the live strategy and the backtest reach the same enter-or-skip decision for that day
