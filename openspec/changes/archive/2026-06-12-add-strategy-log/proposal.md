## Why

The only window into a running strategy is `monitor.pl`, which renders real-time state but keeps
**no history** — once a value scrolls past it's gone, and there's no record of what configuration
a run actually used or what the strategy did at a given minute. We want the live monitor for
watching and a **persistent per-strategy log for the record**.

This must be **generic to every strategy**, not tied to one strategy or to paper mode: each
strategy writes its own daily log that **opens with the exact settings it picked up for the run**
(so a run is reproducible from its log header) and then narrates its execution minute by minute.
The same mechanism SHALL apply to live runs later — only the mode label differs.

## What Changes

- Add a `strategy-log` capability: every strategy emits its own log, written to one file per
  strategy per trading day (e.g. `logs/<strategy_id>/<YYYY-MM-DD>.log`).
- **Run-start configuration header**: when a strategy run begins, it logs the resolved settings /
  params it picked up (the effective config snapshot) plus its identity and run mode
  (paper / live), so the file is self-describing and the run is reproducible from it.
- **Per-minute heartbeat**: roughly once per minute while running, the strategy emits a structured
  snapshot of its current state and open positions. The common fields are strategy-agnostic;
  a strategy MAY contribute extra fields (e.g. `supertrend_short` adds SuperTrend direction, the
  open leg, MTM, and stop distances — mirroring the monitor).
- **Decision log**: every trading action (open / scale / flip / stop / square-off / etc.) is
  logged with its reason at the moment it happens, on the same timeline.
- Mode-agnostic by construction: paper now, live later, with no change to the log format beyond
  the mode label.
- Uses `structlog` (project convention — no bare `print`/`rich`); the daily file is an additional
  sink, not a replacement for stdout logging.

## Capabilities

### New Capabilities

- `strategy-log`: per-strategy daily run log — config header at start, heartbeat + decisions during.

## Impact

- Touches the strategy host / strategy base so any strategy gets the log for free, plus a small
  daily-file sink. `supertrend_short` contributes its strategy-specific heartbeat fields.
- Depends on the same internal state the monitor uses and (for `supertrend_short` stop distances)
  on `add-strategy-risk-controls`.
- Complements, does not replace: `monitor.pl` = live view; `paper-journal` = fills/P&L ledger to
  Mongo; this = human-readable per-strategy daily narrative, paper or live.
- Output-only / observability; no effect on trading decisions.
