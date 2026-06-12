## 1. Daily file sink (base)

- [x] 1.1 Add a per-strategy `structlog` logger writing to `logs/<strategy_id>/<YYYY-MM-DD>.log` (IST date), append mode
- [x] 1.2 Roll to a new file on IST date change; mid-day restart continues the same file
- [x] 1.3 Wire the sink at the strategy-host / `Strategy` base so every strategy gets it

## 2. Run-start config header

- [x] 2.1 At run start, log the effective resolved config (merged params + relevant settings), `strategy_id`, `mode` (paper/live), timeframe, watchlist
- [x] 2.2 Emit once as the first lines of that run's day file

## 3. Heartbeat

- [x] 3.1 Fire on each 1-minute bar close of the primary instrument (fall back to 60s timer); gate to the trading window
- [x] 3.2 Common payload: identity, mode, open positions, day P&L
- [x] 3.3 `heartbeat_fields()` hook for strategy-specific fields; `supertrend_short` adds ST direction/value/bar-time, open leg, MTM, stop distances

## 4. Decision log

- [x] 4.1 `log_decision(action, reason, **fields)` helper on the base
- [x] 4.2 `supertrend_short` calls it on open / scale / flip / leg_stop / day_stop / square_off

## 5. Tests

- [x] 5.1 Config header written once at run start with the resolved params + mode
- [x] 5.2 Heartbeat ~once/min within the window, not outside; strategy-specific fields present for supertrend
- [x] 5.3 Each action emits a decision line with its reason
- [x] 5.4 File path is `logs/<strategy_id>/<date>`; date rollover opens a new file; restart appends
- [x] 5.5 A strategy with no overrides still gets header + common heartbeat + decisions

## 6. Validation

- [x] 6.1 `openspec validate add-strategy-log --strict`
- [x] 6.2 Paper smoke run: a day file shows config header + heartbeats + decision lines
