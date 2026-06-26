## Why

The user maintains a discretionary multi-timeframe option-selling playbook (`strategies/MultiTimeFrameSelling.txt`): form a directional **bias** from many signals (VIX gate, 1h/15m/5m EMA alignment, daily+weekly Camarilla pivots, swing PDH/PDL/PWH/PWL, VWAP, 15m ORB, PCR), and let the bias *strength* dictate a PE:CE **lot ratio** strangle (complete-bull = sell 5 ATM CE … neutral ≈ 1:1 … complete-bear = sell 5 ATM PE). The system today can only model a single 1 PE + 1 CE SuperTrend strangle and has no codified bias engine, no VIX/PCR in the backtest, and no multi-leg ratio simulator. To trade this with confidence it must be codified, **proven on a multi-year NIFTY backtest with walk-forward (out-of-sample) optimization**, and only then promoted to paper.

## What Changes

- New **bias-scoring engine** `src/pdp/signals/bias.py`: a pure, side-effect-free scorer shared by backtest and live. Each signal casts a weighted vote in {−1, 0, +1}; the total maps to one of **7 bias buckets** → a PE:CE lot ratio. VIX and PCR **gates** are encoded here so backtest and live decide identically.
- New **multi-leg ratio-strangle backtest simulator** `src/pdp/backtest/strangle_sim.py` + `StrangleConfig`: N PE + M CE legs at independent strikes, two strike-selection methods (premium-based `>50`, delta-based `0.6Δ`), rollup when premium `<20`, take-profit at % of credit, premium-doubled exit, EMA-flip adjustment, and a ₹15,000 daily-loss cap.
- New **VIX + PCR data in the backtest**: India VIX history backfilled from Dhan into `market_bars`; PCR derived per-bar from `option_bars` OI.
- New **data foundation** (Dhan → Mongo only; no Abi/DuckDB): extend the NSE holiday calendar to 2021–2022, backfill spot + options as deep as Dhan allows, and a coverage-audit script that establishes the **real** tradable horizon.
- New **runner + walk-forward optimizer**: `backtest/strangle_run.py` (single + grid) and `backtest/strangle_walkforward.py` (in-sample optimize, out-of-sample validate; IS-vs-OOS report is the go/no-go gate).
- New **paper strategy** `src/pdp/strategies/directional_strangle.py` + `strategies/directional_strangle.yaml`, reusing the same `bias.py` engine so live == backtest. Paper-first; gated on the OOS backtest being profitable.

## Capabilities

### New Capabilities
- `directional-strangle`: bias-scoring engine, multi-leg ratio-strangle simulator, VIX/PCR backtest data, walk-forward optimizer, and the paper strategy.

### Modified Capabilities
- None of the existing option-selling backtest specs change behavior; the new simulator is additive (`strangle_sim.py` alongside `sim.py`).

## Impact

- New `src/pdp/signals/bias.py`, `src/pdp/signals/__init__.py` — shared bias engine + `BiasWeights`/`BiasResult`.
- New `src/pdp/backtest/strangle_sim.py`, `src/pdp/backtest/strangle_config.py` — simulator + config dataclass.
- New `backtest/strangle_run.py`, `backtest/strangle_walkforward.py`, `backtest/configs/strangle_*.yaml`.
- New `scripts/backfill_vix.py`, `scripts/audit_strangle_data.py`.
- New `src/pdp/strategies/directional_strangle.py`, `strategies/directional_strangle.yaml`.
- Modify `src/pdp/settings.py` (holiday-calendar path / VIX security id), `Taskfile.yml` (new task targets), `data/calendars/` (extend holidays to 2021–2022).
- Reuse `src/pdp/backtest/{sim.py,day_loader.py,chain_loader.py,commissions.py,resample.py}`, `src/pdp/options/{greeks.py,analytics.py,gap_backfill.py}`, `src/pdp/strategies/supertrend_short.py`, `src/pdp/strategy/{abc.py,context.py,strikes.py}`, the IndicatorEngine.
- Tests: `tests/signals/test_bias.py`, `tests/backtest/test_strangle_sim.py`.
- No new external dependencies; no new database tables (VIX rows reuse `market_bars`).
