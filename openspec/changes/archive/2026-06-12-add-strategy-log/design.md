# Design — Per-strategy daily run log

## Generic, not strategy-specific

The log lives at the strategy-host / `Strategy` base level so **every** strategy gets it without
bespoke code. The base provides:

- the daily file sink (open/rotate by IST date),
- the config-header writer (called once at run start),
- the heartbeat scheduler and a common heartbeat payload (identity, mode, open positions, P&L),
- a `log_decision(action, reason, **fields)` helper.

A strategy MAY override a hook (e.g. `heartbeat_fields() -> dict`) to add its own snapshot fields.
`supertrend_short` returns SuperTrend direction/value/bar-time, the open leg, MTM, and stop
distances — the same data the monitor shows. Strategies that don't override get the common fields.

## Run-start configuration header

At run start the strategy logs the **effective** config it resolved — the merged YAML `params`
plus any settings/env that affected the run — as structured key/values, with `strategy_id`, run
`mode` (paper/live), signal timeframe, and the watchlist. Goal: the run is reproducible from the
header alone. Emitted once, as the first lines of the day's file for that run.

## Cadence source

Heartbeat fires on each **1-minute bar close** of the strategy's primary instrument (deterministic
and replay-safe), falling back to a 60s timer if 1m bars aren't subscribed. Gated to the trading
window so off-hours produce no noise.

## File / sink

- Path `logs/<strategy_id>/<YYYY-MM-DD>.log` (IST date), append mode, created on first write of the
  day for that strategy → naturally one file per strategy per day, rotated by the date in the path.
- A dedicated structlog logger per strategy so these lines don't have to be grepped out of the main
  stdout JSON stream; stdout logging is unchanged.
- Append so a mid-day restart continues the same file. Date rollover opens a new file.

## Mode-agnostic (paper now, live later)

Nothing in the format or sink assumes paper. The only mode-dependent element is the `mode` field in
the config header and heartbeat. When live is wired, the same base logging applies unchanged.

## Relationship to other capabilities

- `monitor.pl` (paper-monitor-cli) = live, ephemeral, 1s poll. This = persistent, per-strategy,
  1-minute record + config header.
- `paper-journal` = structured fills + daily P&L stats in Mongo (machine ledger). This =
  human-readable narrative of config + state + decisions.
- `supertrend_short` stop-distance fields reuse the MTM/day-P&L from `add-strategy-risk-controls`.
