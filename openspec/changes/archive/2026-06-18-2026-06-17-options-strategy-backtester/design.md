## Context

PDP's existing backtest engine (`src/pdp/backtest/`) is designed for indicator-based directional strategies: it reads OHLCV bars, applies strategy signals, and simulates order execution. The engine components include:
- `engine.py` — orchestration
- `sim.py` — tick/bar simulation (DO NOT MODIFY — in-flight change)
- `strategy_config.py` — YAML config parser (DO NOT MODIFY — in-flight change)
- `day_loader.py` — data loading (DO NOT MODIFY — in-flight change)
- `models.py` — result models
- `commissions.py` — commission calculation
- `routes.py` — read-only result endpoints (defined but NOT registered)

Historical options data is in MongoDB: `option_bars` (intraday OHLCV per strike/expiry/type) and `expired_option_bars` (archived post-expiry). The `backtest_multiday.py` script (58KB, root-level) is the main CLI runner.

The options strategy backtester is a **new, additive module** that sits alongside the existing engine. It does NOT modify the existing engine files.

## Goals / Non-Goals

**Goals:**
- Support parametric multi-leg options strategy backtesting (StockMock-equivalent).
- Support SL/target (combined and per-leg, in % or absolute points).
- Support trailing SL with configurable trail step.
- Support re-entry (re-open same structure after SL, max N times per day).
- Support strike selection: ATM±N, by-premium (closest to target premium), by-delta.
- Provide results via API and frontend.

**Non-Goals:**
- Modifying the existing indicator backtest engine (guarded files).
- Real-time strategy simulation (that's the paper broker).
- Greek-based exit conditions (future enhancement).
- Adjustment strategies beyond simple roll (future enhancement).
- Options strategy optimization/sweep (future proposal building on this + #5).

## Decisions

### D1: Options strategy configuration schema

```yaml
# backtest/configs/options_example.yaml
type: options-strategy            # discriminator vs indicator strategies
name: "Short Straddle 9:20"
underlying: NIFTY
date_range:
  from: "2026-01-01"
  to: "2026-06-01"
expiry_selection: weekly          # weekly | monthly | nearest

entry:
  time_ist: "09:20"
  legs:
    - type: CE
      side: SELL
      lots: 1
      strike_selection:
        method: atm_offset        # atm_offset | by_premium | by_delta
        offset: 0                 # ATM
    - type: PE
      side: SELL
      lots: 1
      strike_selection:
        method: atm_offset
        offset: 0

exit:
  time_ist: "15:10"              # forced square-off time

risk:
  combined_sl:
    type: points                  # points | percent
    value: 50                     # SL if combined P&L exceeds -50 points
  combined_target:
    type: points
    value: 30                     # target if combined P&L exceeds +30 points
  per_leg_sl: null                # optional per-leg SL
  trailing_sl:
    enabled: true
    trail_after: 20               # start trailing after 20 points profit
    trail_step: 5                 # trail by 5 points
  re_entry:
    enabled: true
    max_count: 2                  # re-enter up to 2 times after SL

lot_size: 75                      # NIFTY lot size
commissions: true                 # apply commission model
```

### D2: Options replay engine is separate from `sim.py`

A new `options_replay.py` module handles bar-by-bar replay of `expired_option_bars`:

```python
class OptionsReplayEngine:
    def run(self, config: OptionsStrategyConfig, bars: dict) -> BacktestResult:
        """
        bars: {date: {(strike, expiry, type): [1m bars sorted by time]}}
        For each trading day:
          1. At entry_time, resolve strikes, open positions
          2. Bar-by-bar: check SL/target/trailing, apply re-entry
          3. At exit_time, force close all positions
          4. Record trades, P&L, equity
        """
```

This engine is independent of the existing `sim.py` — no shared mutable state, no import of guarded files.

### D3: Strike resolution at entry time

At entry time, the engine resolves the actual strike for each leg based on the selection method:
- `atm_offset`: Find ATM strike (closest to spot), apply offset (+/-N strikes)
- `by_premium`: Find the strike whose premium is closest to the target value
- `by_delta`: Find the strike whose delta is closest to the target value (requires delta in bars)

Spot price is taken from `market_bars` at the entry time.

### D4: Results model

```python
@dataclass
class OptionsBacktestResult:
    config_name: str
    date_range: tuple[date, date]
    total_pnl: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    equity_curve: list[dict]          # [{date, cumulative_pnl}]
    daily_pnl: list[dict]             # [{date, pnl, trades, re_entries}]
    weekday_stats: dict               # {monday: {avg_pnl, win_rate, count}, ...}
    trade_log: list[dict]             # [{date, entry_time, exit_time, legs, pnl, exit_reason}]
    commissions_total: float
```

### D5: Synchronous-first, async later

The `POST /api/v1/backtests/run` endpoint runs the backtest synchronously and returns results. When proposal #5 (job runner) ships, this endpoint migrates to submit an async job and return a job ID. The endpoint signature stays the same — the response either contains results directly or a `job_id` for polling.

### D6: Frontend backtest page layout

```
┌───────────────────────────────────────────────────────┐
│ Options Strategy Backtester                           │
├─────────────────────┬─────────────────────────────────┤
│ Strategy Config     │  Results                        │
│ ┌─────────────────┐ │  ┌─────────────────────────────┐│
│ │ Underlying: [▼] │ │  │ Equity Curve (recharts)     ││
│ │ Entry: 09:20    │ │  │ ─────────────────────       ││
│ │ Exit:  15:10    │ │  └─────────────────────────────┘│
│ │ Expiry: Weekly  │ │  Total P&L: ₹1,23,450          │
│ │                 │ │  Win Rate: 62%                  │
│ │ Legs:           │ │  Max DD: -₹45,000               │
│ │ CE SELL ATM +0  │ │  Sharpe: 1.24                   │
│ │ PE SELL ATM +0  │ │  ┌─────────────────────────────┐│
│ │ [+ Add Leg]     │ │  │ Day-wise P&L Table          ││
│ │                 │ │  │ Weekday Stats               ││
│ │ SL: 50pts comb  │ │  │ Trade Log                   ││
│ │ Target: 30pts   │ │  └─────────────────────────────┘│
│ │ Trail: 20/5     │ │                                 │
│ │ Re-entry: 2x    │ │                                 │
│ │ [▶ Run Backtest]│ │                                 │
│ └─────────────────┘ │                                 │
└─────────────────────┴─────────────────────────────────┘
```

## Risks / Trade-offs

- **`expired_option_bars` data coverage**: Multi-leg replay requires strike/expiry coverage for the chosen strategy. If a strike was not captured (gap in backfill), the engine must handle missing data gracefully — skip the day and log a warning.
- **Performance**: A 6-month backtest with 1-minute bars across multiple strikes could be slow (seconds to minutes). The synchronous-first approach may time out for large date ranges. Document the expected latency and recommend capping at 3 months for synchronous mode.
- **In-flight change collision**: This proposal explicitly avoids modifying `sim.py`, `strategy_config.py`, `day_loader.py`. The options replay engine is fully independent.

## Migration Plan

1. Create `options_strategy.py` with config schema (Pydantic model for YAML parsing).
2. Create `options_replay.py` with the replay engine.
3. Add `POST /api/v1/backtests/run` to `routes.py`.
4. Register `backtest.routes.router` in `main.py`.
5. Write tests with mock `expired_option_bars` data.
6. Create example YAML config.
7. Build frontend backtest page.

## Open Questions

- **`expired_option_bars` schema**: Verify field names (strike, expiry, option_type, open, high, low, close, oi, iv, volume) before implementation.
- **Delta in bars**: Strike selection by-delta requires delta values in `expired_option_bars`. If absent, by-delta falls back to by-premium with a warning.
