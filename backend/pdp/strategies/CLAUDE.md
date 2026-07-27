# strategies/ — Concrete Strategy Implementations

Python implementations of trading strategies. Each file implements a class that extends `pdp.strategy.base.BaseStrategy`.

## Files

| File | Purpose |
|------|---------|
| `supertrend_short.py` | `SuperTrendShort` — ST(10,2)/15m NIFTY OTM-1 option-selling |
| `directional_strangle.py` | `DirectionalStrangle` — bias-driven multi-leg ratio strangle; reuses `pdp.signals.bias.score_bias()`; hedge via Rs 2–5 premium-band scan; momentum disabled by default |
| `intraday_directional.py` | `IntradayDirectional` — intraday directional option seller (sell PE in an uptrend / CE in a downtrend); delegates every decision to `pdp.signals.intraday_directional`, the same pure core `pdp.backtest.intraday_sim` calls; ORB + session-VWAP + ST(10,2) + EMA9/20 entry gate, 15-min 3→6→9 scale-in ladder, 8 exit rules, rollup-to-ATM on premium decay |

## Wiring

Strategies are **not** auto-discovered from this package. They are loaded by `StrategyHost` via YAML config files in `strategies/*.yaml` (root level):

```yaml
# strategies/supertrend_short.yaml
class: pdp.strategies.supertrend_short.SuperTrendShort
```

`StrategyHost` imports the class from the dotted path in `class:`, instantiates it, and calls `on_bar()` for every relevant tick.

## Adding a strategy

1. Create `src/pdp/strategies/my_strategy.py` extending `BaseStrategy`
2. Create `strategies/my_strategy.yaml` (root YAML configs folder) with `class: pdp.strategies.my_strategy.MyStrategy`
3. Restart API — `StrategyHost` auto-loads all `*.yaml`

## Key constraint

All indicator state (SuperTrend values, ATR, etc.) comes from `IndicatorEngine` — strategies do **not** recompute indicators.

## Live/backtest parity seam

`directional_strangle.py` and `intraday_directional.py` both delegate every *decision* to a
pure, no-I/O core in `pdp/signals/` (`bias.py`, `intraday_directional.py`) that the matching
backtest engine calls too. The strategy module owns only I/O: reading indicators, resolving
strikes, placing/reconciling orders, persisting leg state. Never re-implement a rule in the
strategy module — put it in the core so both paths get it.

`tests/test_intraday_parity.py` drives one synthetic day through *both* input builders and
asserts the `IntradayInputs` are field-for-field identical. It has already caught a real
look-ahead bug (the loader indexed the 15m confirmation bar at its bucket start, 15 minutes
before it closed). Two rules keep the paths equal and are load-bearing:

- **The opening range is gated on the clock, not on arrival.** The 15m ORB bar and the 5m bar
  that closes with it (09:25) close at the same instant and inter-timeframe dispatch order is
  not guaranteed, so both paths expose the range only from `orb_start + orb_minutes`.
- **Confirmation-timeframe reads are snapshotted at their bar's close**
  (`_snapshot_confirmation` / `_confirmation_as_of`), never read live from the engine at
  decision time — same reason.

## Leg tracking invariants (`directional_strangle.py`, `intraday_directional.py`)

- **One leg per security.** Open legs live in `self._legs: dict[security_id, OpenLeg]`; `_add_leg`
  raises on a duplicate `security_id` rather than allowing two `OpenLeg`s to track the same broker
  position. `_short_legs`/`_hedge_legs`/`_momentum_legs` are read-only properties derived from
  `_legs`, kept for call-site compatibility — always write through `_add_leg`/`_remove_leg`, never
  append to those properties directly.
- **Lock discipline.** Both the open path and the close path acquire `_lock_for(sid)` around the
  broker `get_net_qty` → `_place` sequence (`_close_leg`, `_partial_close`, `_open_short`/`_open_hedge`/
  `_open_momentum`). `asyncio.Lock` is not re-entrant: `_roll_leg` releases the `_rolling` claim
  *before* calling `_close_leg`/`_open_short` so the close and reopen each acquire the sid lock fresh
  rather than nesting.
- **Divergence is surfaced, not silently corrected.** When in-memory `leg.lots` and broker `net_qty`
  disagree, `LEG_STATE_DIVERGED` is emitted and only the smaller of the two is closed — the code never
  closes more than the broker actually holds. A `close_lots == 0` residual (broker holds a sub-lot
  amount) flags divergence and leaves the leg tracked rather than marking it closed.
- **Leg type is durable, not inferred.** `leg_kind` (`short`/`hedge`/`momentum`) is written to the
  `strategy_leg` table on open and read back on `_rehydrate_legs` — a broker `net_qty` sign alone
  cannot distinguish a long hedge from a long momentum leg. An orphan `Position` with no matching
  `strategy_leg` row is adopted by sign inference as a best effort and flagged `LEG_TYPE_UNKNOWN`.
- **An unresolved entry price must never silently discard a real fill.** These helpers now live
  once, in `pdp/strategy/fills.py`, and *both* strategies call them — duplicating them is exactly
  what left `_open_hedge`/`_open_momentum` without the cancel-confirmation fix `_open_short` had
  (2026-07-25 review). `_open_short`/`_open_hedge`/
  `_open_momentum` all share `_confirm_fill_or_recover(sid, order)`: if `_await_fill_avg_px` can't get
  a price within budget, it cancels the entry order and — only if the cancel *didn't* take effect
  (the order already filled, or fills concurrently with the cancel) — checks the broker's own
  `get_position` avg (never an LTP estimate, which would be available whether or not this specific
  order actually filled) and registers the leg from the real fill instead of orphaning it. See
  `strangle-orphan-fill-reconciliation`.
- **Reconciliation runs unattended.** `_reconcile_loop` (started in `on_init`, cancelled in
  `on_shutdown`) calls `_reconcile_divergences()` on a fixed interval (`reconcile_interval_s`, default
  60s) for the strategy's whole lifetime — not only when `state()` is polled over HTTP, closing the
  gap where an orphan/diverged position could sit undetected indefinitely with nobody watching the
  console.
