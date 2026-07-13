# bias-input-completeness

## Why

The directional strangle sizes every position from `score_bias()`, a weighted vote across eight
inputs. Three of those eight are silently dead in live trading. The strategy is not trading the
strategy that was backtested.

`_build_bias_inputs` (`backend/pdp/strategies/directional_strangle.py:689`):

```python
pivot = ind.pivots(self.sid, "5m")            # :696
cam_daily = _to_cam(pivot)                    # :697
weekly_pivot = ind.pivots(self.sid, "1w")     # :700
cam_weekly = _to_cam(weekly_pivot)            # :701
pcr = self.ctx.chain_hub.get_pcr(self.underlying) if self.ctx.chain_hub else None  # :706-708
```

1. **`cam_daily` is not daily.** It reads the pivot tracker on the **5-minute** timeframe. A
   Camarilla pivot is computed from the *prior period's* HLC, so a 5m pivot describes the previous
   five minutes, not the previous day. The vote weighted `w_cam_daily: 1.0` is a five-minute
   micro-level dressed as a daily level. `1D` is already in every watchlist and already carries
   `family: pivots` — the correct value is one string away.

2. **`cam_weekly` is always `None`.** It reads the `1w` timeframe, but no watchlist declares `1w`:
   all three configs list `timeframes: [5m, 15m, 30m, 1H, 1D]`. `IndicatorEngine` only builds
   trackers for configured `(sid, tf)` pairs, so `ind.pivots(sid, "1w")` returns `None` on every
   call, forever. `w_cam_weekly: 1.0` contributes exactly zero. The comment at `:699` — "read from
   `1w` pivot snapshot (seeded by 1w BarAggregator)" — describes a wiring that does not exist.

3. **`pcr` is `None` for SENSEX.** `settings.py:87` sets
   `OPTIONS_UNDERLYINGS: str = '["NIFTY","BANKNIFTY"]'`, and the key **is present in
   `backend/.env`**, so the `.env` value wins and a code-only edit is a no-op. SENSEX has no chain
   poller, so `chain_hub.get_pcr("SENSEX")` returns `None` and `w_pcr: 1.0` is dead for that
   underlying. `WAREHOUSE_UNDERLYINGS` (`settings.py:113`) defaults to `["NIFTY"]` alone, so SENSEX
   and BANKNIFTY chains are not warehoused either.

The failure mode that ties these together is the one worth fixing structurally: **a strategy can
assign a non-zero weight to an input its own configuration cannot supply, and nothing complains.**
`score_bias` treats a `None` vote as an abstention and silently renormalises. A weight of 1.0 on a
permanently-absent input is indistinguishable, from the logs, from a genuinely neutral market.

Two of the three dead inputs pull toward *neutral*, and `neutral: [3, 3]` in the ratio table is the
most-traded bucket. The live strategy has been systematically more neutral than its backtest, which
supplies all eight inputs from the warehouse.

## What Changes

- **Read daily Camarilla from the daily bars.** `_build_bias_inputs` reads `ind.pivots(sid, "1D")`.
  `1D` is already configured with `family: pivots`; no config change is required for this input.

- **Add `1w` to the watchlist** of all three live strangle configs and their backtest counterparts,
  with `family: pivots`, so `cam_weekly` has a tracker to read. `BarAggregator` already produces 1w
  bars (`_bar_boundary_1w`, `bars.py:72`); only the watchlist declaration is missing.

- **Give SENSEX a chain.** Add `SENSEX` to `OPTIONS_UNDERLYINGS` **in `backend/.env` and in
  `settings.py:87`** — the `.env` value wins, so changing only the code default is a silent no-op.
  Set `WAREHOUSE_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"]` (`settings.py:113`).

- **Fail startup when a strategy weights an input it cannot supply.** At strategy load, for every
  bias weight greater than zero, assert the corresponding input is satisfiable from the watchlist and
  settings: `w_cam_daily` needs `1D` + `pivots`; `w_cam_weekly` needs `1w` + `pivots`; `w_ema_1h`
  needs `1H` + `ema`; `w_pcr` needs the underlying in `OPTIONS_UNDERLYINGS`; `w_swing` needs
  `period_levels`. Raise with the offending `(weight, missing requirement)` named. This is the
  requirement that keeps the class of bug from recurring — every specific fix above is one instance
  of it.

- **Log the bias vote breakdown.** `score_bias` already computes per-input votes; emit them once per
  bias evaluation (`cam_daily=+1 w=1.0`, `pcr=abstain`, …) so an abstaining input is visible in the
  session log rather than inferred from a suspicious bucket distribution.

## Impact

- **Affected specs:** `bias-input-completeness` (new). Amends `openspec/specs/strategy-registry/spec.md`.
- **Affected code:** `backend/pdp/strategies/directional_strangle.py:689-727`
  (`_build_bias_inputs`), `backend/pdp/signals/bias.py` (vote breakdown emission),
  `backend/pdp/strategy/host.py` (startup satisfiability check),
  `backend/strategies/directional_strangle_*.yaml` (+ `1w`),
  `backend/backtest/configs/strangle_*.yaml` (+ `1w`), `backend/pdp/settings.py:87,113`,
  `backend/.env` (`OPTIONS_UNDERLYINGS`).
- **`.env` is not in git and its value wins.** `OPTIONS_UNDERLYINGS` must be edited on every
  deployment target. Verify after deploy by asserting `chain_hub.get_pcr("SENSEX")` is non-null
  during market hours, not by reading the source.
- **Strategy behaviour will change, on purpose.** Restoring two neutral-leaning abstentions and one
  live PCR vote shifts the bucket distribution. Re-run the three strangle backtests **after**
  `bar-session-anchoring` and `indicator-history-depth` land, and compare the bucket histogram, not
  just the P&L.
- **The weekly pivot needs history.** `1w` at 200-bar depth is ~4 years of weekly bars. Confirm
  `market_bars` can supply it before enabling `w_cam_weekly`; if not, the startup check will fail
  loudly, which is the intended behaviour.
- **Depends on `bar-session-anchoring` and `indicator-history-depth`.** Wiring an input to bars that
  are mis-anchored or under-seeded trades one silent error for another. Ties into
  [[directional_strangle]] and [[live_backtest_parity]].
