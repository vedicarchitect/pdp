# strangle-drop-unused-vwap-watchlist

## Why

Live-verified 2026-07-20 (Dhan token refreshed, markets open): `Indicators` readiness was
permanently `blocked` — `"Unseeded: VWAP on 5m, VWAP on 15m"` — for all three strangles
(NIFTY/BANKNIFTY/SENSEX), independent of the earlier Dhan-token outage and independent of the
already-fixed 1m-reconciliation/EMA-depth gaps.

Root cause: each strangle's watchlist (`backend/strategies/directional_strangle_{nifty,banknifty,
sensex}.yaml`) configures `family: vwap` on the **spot index** security_id (e.g. NIFTY `"13"`).
`VWAPTracker.update()` only accumulates ΣPV/ΣV when `volume > 0`
([vwap.py:44](../../../backend/pdp/indicators/vwap.py#L44)) — Dhan's index feed carries **zero
volume** (indices aren't directly traded), so this tracker structurally can never converge, on any
timeframe, regardless of warmup depth or feed health. `IndicatorEngine.seeding_summary` correctly
reports it as permanently unseeded, and `check_readiness`'s Indicators component
([directional_strangle.py:462-475](../../../backend/pdp/strategies/directional_strangle.py#L462-L475))
correctly blocks on it — the gate is working as designed; the watchlist config feeding it is wrong.

Confirmed neither `pdp/signals/bias.py` nor `pdp/strategies/directional_strangle.py` reads VWAP at
all — it was configured for Indicator Matrix / console display only (the matrix's own cell builder
already reads VWAP from the **futures** contract sid instead of the index sid, for exactly this
reason — see [routes.py:540-542](../../../backend/pdp/strategy/routes.py#L540-L542)). The strategy
watchlist was never updated to match, so a display-only, unconsumed family has been silently
blocking every paper/live entry for all three strangles.

The correct long-term fix — point VWAP at each underlying's futures contract sid, matching the
matrix — is deferred: `market_bars` has no historical futures-contract data, so backtest cannot
compute VWAP-on-futures for parity today. Enabling it live-only would let live and backtest diverge
silently, which the project's paper-first/backtest-parity discipline does not allow. That work
(futures `market_bars` ingestion + backfill) is separate and out of scope here.

## What Changes

- Remove `family: vwap` from the `sid`-13/`25`/`51` (index) watchlist entries in the three strangle
  YAMLs. VWAP is not read by `bias.py` or the strategy, so removing it has no scoring effect —
  it only unblocks the `Indicators` readiness component.
- Add a code comment at each removed entry (and/or a short note in
  `backend/strategies/CLAUDE.md`) recording *why* it's absent and the re-enable condition: once
  futures `market_bars` history exists, re-add `vwap`/`vwma` keyed to the futures contract sid
  (matching `_build_indicator_cell_inproc`'s `fut_sid` pattern), not the index sid.
- No change to `IndicatorEngine`, `seeding_summary`, or the readiness gate logic itself — the gate
  is correct; only the watchlist input was wrong.
- VWAP remains available for the Indicator Matrix / console display via the existing
  `matrix_suites_configured` futures-sid registration (`groups.py`) — that path is untouched and
  already correct.

## Impact

- Affected specs: `strangle-observability-gaps` (clarify that the Indicators readiness component
  only gates on families the strategy's watchlist configures, and that watchlist entries must be
  volume-bearing for volume-anchored families).
- Affected code: `backend/strategies/directional_strangle_nifty.yaml`,
  `backend/strategies/directional_strangle_banknifty.yaml`,
  `backend/strategies/directional_strangle_sensex.yaml` (remove one watchlist line each). No
  Python code changes required — `bias.py`/`directional_strangle.py` never referenced `vwap`.
- Follow-up (not in this change): futures `market_bars` ingestion/backfill, then re-add
  VWAP/VWMA on futures sid to both backtest and live watchlists together for parity.
