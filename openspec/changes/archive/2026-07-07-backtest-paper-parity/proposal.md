# backtest-paper-parity

## Why

The backtest and paper stacks **share the same bias-scoring code**
(`pdp/signals/bias.py::score_bias`, called by both `strangle_sim` and `directional_strangle`),
so the strategy logic is not the source of divergence — **input fidelity is**. Exactly one
bias input genuinely differs between the two paths, and one radar signal is pure noise:

1. **VWAP is the one genuinely-divergent bias input.** Live VWAP prefers the front-month
   **futures** SID for real volume (`directional_strangle.py:629-631`, `vwap_sid = self._futures_sid or self.sid`), while the backtest has **no futures data at all** and computes an
   equal-weighted spot typical-price VWAP (`strangle_loader.py:178-227`, `_VWAP` "equal-weights
   bars when volume is absent"). Same code, structurally different VWAP number → the two paths
   can score the same bar differently purely because of VWAP. VWAP carries a low weight
   (`w_vwap=1.0`, one vote among many in `bias.py:100,312`), so removing it is expected to be
   immaterial to the ₹1.35cr result — and it removes the divergence at the source.

2. **The "futures missing" radar flag is perpetual noise.** `completeness.py:24-26,33`
   registers a `futures` family that has **no ingested source** and is therefore reported
   `"futures missing"` for **every** (index, date) — `_futures_family` in `coverage.py:181-185`
   literally always returns missing. This floods `/data:coverage` and the vs-paper `cause`
   field, masking the real divergences we actually need to attribute.

3. **No daily convergence measurement.** The `backtest-paper-comparison` capability already
   exposes `/runs/{id}/vs-paper` (per-day backtest−paper divergence with attributed causes),
   but nothing turns it into a **daily convergence check** that tracks whether paper is
   actually walking toward the backtest-proven ~₹1.35cr/5yr trajectory as paper accumulates.

**Decision (locked with user): drop VWAP/VWMA from the bias inputs entirely on both paths.**
This eliminates the single genuine input divergence at the source and removes any need to
warehouse futures data. With no VWAP consumer, the whole futures SID path is dead and the
perpetual "futures missing" radar noise disappears with it.

## What Changes

- **Remove VWAP/VWMA as a bias input on both paths.** Drop the `vwap` field, the `w_vwap`
  weight, `_vwap_vote`, and the `vwap` ratio-table entry from `pdp/signals/bias.py`
  (`:70-71,100,217-222,312`). Remove the live VWAP assembly + `futures_sid` VWAP sourcing from
  `directional_strangle.py` (`:150-160,205,290,629-631,649`) and the backtest `_VWAP`
  computation from `strangle_loader.py` (`:178-227`). The bias score is then computed from the
  same set of inputs on both paths, with no structurally-divergent input remaining.
- **Reconfirm ₹1.35cr holds without VWAP.** Re-run the multi-index sweeps and record the new
  net/PF/MaxDD per index; VWAP carried one low vote, so the expectation is no material
  regression. If any index regresses materially, stop and surface it (do not silently proceed).
- **Drop the futures SID path entirely.** With no VWAP consumer,
  `_resolve_front_month_futures_sid` (`directional_strangle.py:67`) and `self._futures_sid`
  become dead code — remove them. No futures collection, backfill, or warehousing is added.
- **Remove the "futures missing" radar family.** Delete the `futures` family from
  `completeness.py` (`RADAR_FAMILIES`, `FAMILY_LABELS`, `FamilyGaps.futures`, `:24-26,33,89,98,104`)
  and from `coverage.py` (`_futures_family`, `:181-185`, and its wiring at `:263,268,284`). The
  radar and the vs-paper `cause` field stop emitting the perpetual `"futures missing"` noise.
- **Wire the vs-paper radar into a daily convergence check.** Add a daily convergence report
  built on the existing `/runs/{id}/vs-paper` that, per index, tracks cumulative
  backtest−paper divergence against the ₹1.35cr/5yr trajectory with attributed causes — the
  measurement loop that tells us when paper is converging.

## Impact

- **Modified specs:** `directional-strangle` (bias-scoring engine no longer takes VWAP),
  `market-data-coverage` (gap radar drops the futures family), `backtest-paper-comparison`
  (daily convergence check added).
- **Affected backend code:** `pdp/signals/bias.py` (drop VWAP field/weight/vote/ratio),
  `pdp/strategies/directional_strangle.py` (drop VWAP assembly + futures SID path),
  `pdp/backtest/strangle_loader.py` (drop `_VWAP`), `pdp/backtest/completeness.py` (drop
  futures family), `pdp/warehouse/coverage.py` (drop `_futures_family` + wiring),
  `backend/backtest/` sweep runners (re-run to reconfirm ₹1.35cr).
- **Reuses (does not reinvent):** the shared `score_bias` function (only its input set
  shrinks), the existing `/runs/{id}/vs-paper` alignment + minute-diff + cause attribution.
- **Out of scope:** any new futures ingestion/warehousing (explicitly not needed once VWAP is
  gone); the live-P&L/ledger work (Change B, already done); backtest-console readability and
  nav (Change D). The VWAP/VWMA **indicator families** remain available for chart display —
  only their role as a **bias decision input** is removed.
- **Prerequisite:** Change B archived first (strict A→B→C→D sequencing).
