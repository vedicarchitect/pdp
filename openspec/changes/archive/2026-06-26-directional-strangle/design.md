## Context

The strategy in `strategies/MultiTimeFrameSelling.txt` is a discretionary directional-strangle seller. We are codifying it so it is testable and tunable, then validating it on a multi-year NIFTY backtest before any paper deployment. PDP is a **standalone** project: all historical data comes from Dhan into Mongo (`market_bars`, `option_bars`) — the sibling Abi DuckDB is not a data source.

## Goals

- Bias logic shared **byte-for-byte** between backtest and live (one module, two callers).
- A simulator that models the actual strangle the playbook describes (ratio legs, rollup, take-profit, adjustment), not a 1:1 approximation.
- Honest validation: walk-forward OOS, no full-sample curve-fitting; the real data horizon is measured, not assumed.

## Key decisions

### 1. Bias as a weighted score → 7 buckets
Each signal contributes a vote `v ∈ {−1, 0, +1}` scaled by a weight `w`. `score = Σ wᵢ·vᵢ`, normalized to `[−1, +1]`. Thresholds split the score into 7 buckets mapped to PE:CE **sell** ratios (lots):

| Bucket | score band | sell PE:CE |
|---|---|---|
| complete-bull | `≥ +0.75` | 0 : 5 (ATM CE) |
| most-bull | `+0.5 .. +0.75` | 4 : 2 |
| more-bull | `+0.2 .. +0.5` | 3 : 2 |
| neutral | `−0.2 .. +0.2` | 1 : 1 (or no-trade, configurable) |
| more-bear | `−0.5 .. −0.2` | 2 : 3 |
| most-bear | `−0.75 .. −0.5` | 2 : 4 |
| complete-bear | `≤ −0.75` | 5 : 0 (ATM PE) |

Rationale: makes the whole system a small set of tunable numbers (weights + thresholds) instead of brittle nested gates, which is what makes walk-forward optimization tractable. Weights, thresholds, and the ratio table all live in `BiasWeights` / config.

### 2. VIX and PCR are hard gates, not votes
Per the playbook, VIX spiking >5%, at day-high, or rising over the last 3×5m bars **blocks** new entries entirely (`gated=True`); it is not a soft vote. PCR >1.1 / <0.9 contributes a vote (bias), but the VIX condition is a gate. Encoding both in `bias.py` keeps backtest and live identical.

### 3. Strike selection: two methods, compared
- `premium`: walk the chain for the nearest strike with premium `> 50` on the relevant side (reuses `chain_loader` + `price_at`). Needs only price data we already have.
- `delta`: solve implied vol from the bar's option premium (Black-Scholes inversion), then use `src/pdp/options/greeks.py` to pick the strike nearest the target delta (0.6Δ). Needs an IV solve per candidate strike.
Both behind a `strike_method` flag so Phase 4 can compare them head-to-head.

### 4. Simulator generalizes `sim.py`, not `OptionsReplayEngine`
`sim.py` already has the loaders, commission model, no-look-ahead `price_at`, rollup, and per-leg MTM we need — but its `legs` is `dict[str, Leg]` (one CE, one PE). We fork its structure into `strangle_sim.py` and generalize to `list[Leg]` keyed by `(opt_type, strike)`, so we can hold multiple strikes per side and rebalance them independently. We do **not** extend `OptionsReplayEngine` (no rollup/scale-in/signal-drive there).

### 5. Exits (from the playbook, made precise)
- **Rollup**: when a leg's premium `< 20`, buy it back and re-sell a new strike with premium ≥ `roll_target_min_prem` (default 50) on the same side.
- **Take-profit**: close a leg at `take_profit_pct` of collected credit (default 50%).
- **Tiered pct stop** (replaced the initial "premium-doubled" rule after A/B testing): close half lots when premium rises 30% above entry (`pct_stop_half`); close all remaining when premium rises 40% above entry (`pct_stop_all`). A 15-minute stop-recovery gate blocks re-entry on that side until the stopped strike's premium comes back below the exit price and sustains there for ≥ 3 consecutive bars. 30-day result: Net +64,210 / PF 2.06 / Win 64% vs +8,589 / 1.13 / 52% with the 2× rule.
- **Adjustment / trend flip**: on 15m or 1h 50-EMA being broken/crossed against the position (9 & 20 crossing opposite), roll the tested side to flatten directional exposure.
- **Daily loss cap**: flatten everything and stop for the day when realized+unrealized ≤ −₹15,000.
- **Square-off**: all legs closed at session end.

### 6. Entry timing
Entries only **after the 10:15 IST 1h candle completes** (playbook rule). The simulator advances on the configured signal timeframe (5m) but holds entries until that gate.

## Risks / trade-offs

- **Dhan historical depth is the binding constraint.** Expired-option history several years back may be shallow; the "5-year" target may resolve to fewer usable years. The Phase-0 audit measures and reports this; the backtest window is set from the audit, not assumed.
- **VIX backfill** is a new, untested Dhan pipeline; if depth is short, the VIX gate is only testable for the covered span (the gate degrades to "always allow" outside it, logged).
- **Overfitting**: many knobs. Mitigated by grouping weights, limiting free parameters, and judging on OOS only.
- **Delta method** depends on an IV solver; sanity-checked against premium-method results and any stored Greeks.

## Migration / rollout

Additive only. The new simulator and strategy live alongside existing ones. The paper strategy ships disabled-by-default behavior is paper-first (`LIVE` unset) and is only promoted after the Phase-4 OOS gate passes.
