# bias-input-completeness — minimal context

Read only these to work this change. **Do not start until `bar-session-anchoring` and
`indicator-history-depth` are applied.**

| File | Why |
|------|-----|
| `backend/pdp/strategies/directional_strangle.py` | `_build_bias_inputs:689-727` — `pivots(sid,"5m")` at `:696`, `pivots(sid,"1w")` at `:700`, `get_pcr` at `:708` |
| `backend/pdp/signals/bias.py` | `BiasInputs:59-75`, `BiasWeights:96-111`, `score_bias:279`, vote table `:297-301` |
| `backend/pdp/strategy/host.py` | Strategy load — where the satisfiability check goes |
| `backend/pdp/settings.py` | `OPTIONS_UNDERLYINGS:87`, `WAREHOUSE_UNDERLYINGS:113` |
| `backend/strategies/directional_strangle_nifty.yaml` | `timeframes:17`, `indicators:18-27`, weights `:91-98` |
| `backend/pdp/indicators/engine.py` | Trackers exist only for configured `(sid, tf)` pairs |

## Key facts established during investigation
- `cam_daily` reads pivots on **`5m`** — a five-minute pivot weighted as a daily level.
- `cam_weekly` reads `1w`, which **no watchlist declares** → always `None`, `w_cam_weekly: 1.0` is dead.
  The code comment at `:699` describes wiring that does not exist.
- `OPTIONS_UNDERLYINGS` is `["NIFTY","BANKNIFTY"]` and **is present in `backend/.env`** — the `.env`
  value wins, so editing `settings.py:87` alone changes nothing. (`BROKER_SYNC_ENABLED`, by contrast,
  is absent from `.env`, which is why the code default governed there.)
- `WAREHOUSE_UNDERLYINGS` defaults to `["NIFTY"]` only.
- `score_bias` treats a null vote as an abstention and renormalises. A weight on a permanently-absent
  input is indistinguishable from a neutral market — that is the structural bug; the three specific
  wiring faults are instances of it.
- Two of the three dead inputs pull toward neutral, and `neutral: [3, 3]` is the most-traded bucket.
  The live strategy has been more neutral than its backtest.

## Related
`[[directional_strangle]]`, `[[live_backtest_parity]]`. Re-baseline the backtests afterwards and
compare the **bucket histogram**, not only P&L.
