## 1. Settings-driven SuperTrend

- [x] 1.1 Add `SUPERTREND_PERIOD` / `SUPERTREND_MULTIPLIER` to `settings.py` (defaults 10 / 2.0)
- [x] 1.2 Wire `IndicatorEngine(...)` in `main.py` to read both from settings

## 2. Retune the paper strategy

- [x] 2.1 `supertrend_short.yaml`: watchlist + `params.timeframe` 5m → 15m
- [x] 2.2 `supertrend_short.yaml`: `leg_stop_per_lot` 1,000 → 3,000, `day_stop` 10,000 → 20,000
- [x] 2.3 Update YAML header + `main.py` comments to reflect ST(10,2)/15m promotion

## 3. Verify

- [x] 3.1 Confirm settings + strategy config load (period 10/2.0, tf 15m, stops 3,000/20,000)
- [x] 3.2 Run settings/strategy/indicator test suites green (58 passed)
- [x] 3.3 Document strategy flow in `docs/supertrend_short_strategy.md` (session/day lifecycle + entry/exit)
