# indicator-history-depth — minimal context

Read only these to work this change. **Do not start until `bar-session-anchoring` is applied.**

| File | Why |
|------|-----|
| `backend/pdp/indicators/warmup.py` | `_TF_WARMUP_CALENDAR_DAYS:51-61` and `_DEFAULT_WARMUP_CALENDAR_DAYS:62` — deleted here; call sites at `:111`, `:148` |
| `backend/pdp/indicators/ema.py` | `EMATracker` computes only the periods it is given; must omit unconverged ones |
| `backend/pdp/indicators/engine.py` | Startup depth summary lands here |
| `backend/pdp/indicators/CLAUDE.md` | Family list + the "compute once, never recompute" rule |
| `backend/strategies/directional_strangle_nifty.yaml` | `periods: [9, 20, 50, 100]` at `:20` — the actual cause of `--` |
| `backend/backtest/configs/strangle_nifty_hedged.yaml` | Must move in lockstep or live/backtest diverge |
| `backend/tests/indicators/test_warmup.py` | `:251-291` import the constants this change deletes |

## Key facts established during investigation
- **EMA(200) is not configured anywhere.** All three live configs stop at period 100. Warmup depth
  was never the cause; the root `CLAUDE.md` troubleshooting row saying otherwise is wrong.
- `_TF_WARMUP_CALENDAR_DAYS` values (15m→40, 30m→45, 1H→90) are nominally generous, but they are
  hand-maintained constants annotated ">> 200" — an assumption that breaks the moment a period grows.
- `_DEFAULT_WARMUP_CALENDAR_DAYS = 1`: a timeframe missing from the map warms up on one day of data,
  silently.
- Warmup seeds from Mongo `market_bars` and succeeds with however few bars it finds. There is no
  signal today distinguishing "converged" from "still converging".

## Related
Depends on `bar-session-anchoring`. Feeds `bias-input-completeness` (which adds the `1w` timeframe
and therefore its own depth requirement).
