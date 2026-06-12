## 1. Bar-time gating

- [x] 1.1 Derive bar IST time from `bar.bar_time` (UTC → IST) in `on_bar`
- [x] 1.2 Replace `_now_ist()` comparisons for `start_t` and `squareoff_t` with the bar IST time
- [x] 1.3 Remove the now-unused `_now_ist()` helper (and its `datetime` import)

## 2. Tests

- [x] 2.1 A bar timestamped before `start_ist` places no order even if wall-clock is later
- [x] 2.2 A bar timestamped at/after `square_off_ist` flattens and stops for the day
- [x] 2.3 Bars within the window behave exactly as before (existing + risk-control tests green)

## 3. Validation

- [x] 3.1 `openspec validate strategy-bar-time-scheduling --strict`
