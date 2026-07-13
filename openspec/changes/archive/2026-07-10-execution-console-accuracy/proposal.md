# execution-console-accuracy

## Why

The Execution tab is the pre-paper cockpit for the directional strangle, but its
Indicator Matrix does not match the trader's Kite/TradingView charts and its event feed is
noise. Both must be trustworthy before the live paper run.

Concretely, versus Kite (params confirmed by the trader: SuperTrend(10,2), EMA 9/20/50/100
on close, PSAR 0.02/0.02/0.2, Camarilla "Auto"):

- The `1D` matrix column is entirely `--` — a 1D bar never closes intraday and warmup has
  no 1D data source, so 1D EMA/ST/PSAR is never seeded (and 1D structural events never
  fire).
- EMA/ST/PSAR differ from Kite because warmup seeds too few bars (EMA100 needs 100; 15m
  warms only ~6 calendar days) and the SuperTrend default is (3,1) not (10,2).
- Camarilla and PDH/PDL/PWH/PWL are wrong: they are read from the drifting live-engine
  `5m` snapshot instead of the already-correct persisted `index_levels` warehouse; weekly
  is never built and there is no per-timeframe mapping (the trader reads 5-15m→daily,
  30m/1H→weekly, 1D→monthly).
- The "Recent Events" list shows only strategy heartbeats (`bias_evaluated`,
  `leg_status`, `leg_open`); the meaningful market-structure detectors (EMA cross,
  SuperTrend flip, Camarilla break) already run and publish to `/ws/events` but never reach
  the sidebar because of three Flutter WS-contract mismatches.
- The matrix also omits indicators the trader relies on: EMA200, VWAP, VWMA, RSI(+signal).
  VWAP/VWMA are volume-anchored and blank on spot indices, so they must be computed on the
  index futures contract.

## What Changes

- **Levels warehouse gains a `monthly` period.** `LevelsStore` computes monthly Camarilla +
  PMH/PML from the prior calendar month; `/api/v1/levels/{underlying}` accepts
  `period=monthly`.
- **The monitor matrix reads levels from `index_levels`, not live-engine state**, and maps
  timeframe→period: `5m/15m`→daily, `30m/1H`→weekly, `1D`→monthly (each carrying its
  Camarilla set and PDH/PDL, PWH/PWL, PMH/PML).
- **Indicator warmup seeds 1D** (via the Dhan daily-candles API) and deepens 15m/1H/1D
  lookback so EMA100 fully seeds; the matrix pins SuperTrend to (10,2).
- **The matrix adds EMA200, VWAP, VWMA, RSI(+SMA signal) columns**; VWAP/VWMA are sourced
  from each index's current-month **futures** contract.
- **1D market-structure events fire** once 1D bars are seeded (no new detector work).
- **The Flutter Live Events sidebar is fixed and promoted**: the three WS-contract
  mismatches (`type` filter, `ts` field, severity case) are corrected, the noisy "Recent
  Events" heartbeat list is removed, and the meaningful event stream drives the sidebar for
  all three indices across all timeframes.

## Impact

- Affected specs: `strategy-execution-monitor` (matrix payload), `levels-warehouse`
  (monthly period), `indicator-warmup` (1D source + depth), `event-feed-ui` (Flutter Live
  Events sidebar contract + promotion).
- Affected code: `backend/pdp/indicators/levels_store.py`, `backend/pdp/strategy/routes.py`,
  `backend/pdp/indicators/warmup.py`, `backend/pdp/events/detectors/*` (optional
  re-source), `app/lib/features/events/*`, `app/lib/features/manage/*`.
- Reuses `pivots._compute_pivots`, `LevelsStore`, existing detectors, and
  `PeriodLevelsTracker` (already tracks PMH/PML). No new pivot math or detectors.
