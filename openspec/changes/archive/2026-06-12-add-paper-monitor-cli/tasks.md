## 1. Dynamic expiry

- [x] 1.1 Add a `next_weekly_expiry()` helper in `monitor.pl` (next Tuesday, today if Tuesday before market close)
- [x] 1.2 Replace the `$CHAIN_EXPIRY` constant with the computed expiry; refresh on date rollover
- [x] 1.3 Replace hard-coded `Jun9` instrument labels with the resolved expiry's label

## 2. Risk-stop display

- [x] 2.1 Read the configured `leg_stop_per_lot` / `day_stop` (from the strategies endpoint params, or a constant matching the strategy default)
- [x] 2.2 Show per-leg stop distance (MTM vs `leg_stop_per_lot × lots`) and a warning colour when within the alert band
- [x] 2.3 Show day realized vs `day_stop` in the totals line

## 3. Validation

- [x] 3.1 `openspec validate add-paper-monitor-cli --strict`
- [x] 3.2 `perl -c monitor.pl` passes; manual run shows the current week's expiry and correct labels
