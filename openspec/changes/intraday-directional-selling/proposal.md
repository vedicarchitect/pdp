# intraday-directional-selling

## Why

`backend/strategies/intraday-directional.md` has specified an intraday directional option-selling
strategy in prose since it was written, with no implementation, no YAML, and no OpenSpec change.
It is a materially different edge from the existing `directional_strangle`:

| | `directional_strangle` | this change |
|---|---|---|
| Decision model | weighted multi-TF vote → 7 buckets → PE:CE ratio | hard 4-condition AND gate per side |
| Position | two-sided ratio strangle | **one** directional short leg at a time |
| Entry window | after 10:15 (1h candle) | after the 09:15–09:30 ORB candle closes |
| Sizing | ratio table × `scale_lots`, sized at entry | 15-minute scale-in ladder 3 → 6 → 9 lots |
| Strike | premium-floor / delta, OTM | ATM or 1–2 **ITM** |
| Exits | TP / tiered pct-stop / rollup / trend-flip | 8 rules incl. sustained EMA20 break, option-chart SuperTrend flip, sustained Camarilla rejection |
| Rollup target | next OTM strike with premium ≥ 50 | **back to ATM** when premium < 20 |

Neither existing backtest engine can express it. `StrangleConfig`/`strangle_sim` is built around
`score_bias()` buckets and a two-sided leg book; the legacy `StrategyConfig`/`sim.py` engine is a
single-indicator SuperTrend replay with no ORB, VWAP, scale-in ladder, or option-chart SuperTrend.
Forcing this strategy into either would corrupt that engine's semantics for the configs already
depending on it.

The repo's one hard-won lesson about strategies that exist on both paths is that live and backtest
drift silently unless they share a **pure decision core** — `pdp/signals/bias.py` is that seam for
the strangle, and even there the `BiasInputs` construction is duplicated on both sides with no
automatic enforcement. This change adopts the same seam and adds the parity test the strangle lacks.

## What Changes

- **New pure decision core** `pdp/signals/intraday_directional.py`: `IntradayInputs`,
  `IntradayParams`, `IntradayState`, `evaluate_entry()`, `evaluate_scale_in()`, `evaluate_exit()`.
  No I/O, no imports from `orders`/`db`/`mongo`. Both paths call it; neither reimplements it.
- **New backtest engine**: `pdp/backtest/intraday_config.py` (`IntradayDirectionalConfig`),
  `pdp/backtest/intraday_loader.py`, `pdp/backtest/intraday_sim.py`, CLI
  `backend/backtest/intraday_run.py`, Taskfile task `backtest:intraday`. Reuses `sim.py`'s
  `DayResult`/`Trade`/`LegRecord`/`price_at`/`select_strike` unchanged, so the whole existing
  warehouse pipeline (`RunWriter`, `aggregate`, `BacktestStore`, decision trace) works untouched.
- **New live strategy**: `pdp/strategies/intraday_directional.py` (`IntradayDirectional(Strategy)`)
  + `backend/strategies/intraday_directional_nifty.yaml`.
- **Shared fill-confirmation helpers** extracted to `pdp/strategy/fills.py` from
  `directional_strangle.py`, called by both strategies, so the cancel/fill orphan-race fix exists in
  exactly one place. (Copy-pasting it is precisely what left `_open_hedge`/`_open_momentum`
  vulnerable until the 2026-07-25 review.)
- **`option_trend_read()`** factored out of `atm_suite.atm_trend_read()` so a *held* strike's own 5m
  SuperTrend(10,2) can be read, not just the ATM strike's.
- **Rollup to ATM**: when the sold option's premium decays below `roll_trigger_prem` (₹20), the leg
  is rolled back to the current ATM strike, same side and same lot count. This adopts
  `_roll_leg`'s all-or-nothing discipline verbatim — every precondition is checked *before* the old
  leg is closed, and a re-open that fails to land a leg raises a naked-position alarm instead of
  reporting success. (The 2026-07-09 leg-growth incident was exactly a close-then-fail-to-reopen.)
- **Hardened invariants inherited, not re-derived**: the eight leg-lifecycle invariants codified in
  `backend/pdp/strategies/CLAUDE.md` ("Leg tracking invariants") are requirements of this strategy
  too — one leg per security, per-sid lock discipline, close-side from the broker sign, never close
  more than the broker holds, durable leg identity, fill-confirmation on unresolved entry price,
  per-security lot cap inside the lock, and unattended reconciliation. Invariant 6
  (fill-confirmation) is implemented **once** in `pdp/strategy/fills.py` and shared.
- **Comparability with the strangle**: same warehouse collections, same metric/verdict definitions,
  same commission model, same lot-size-by-date table, same decision vocabulary — so the two
  strategies can be put side by side over one window with no reconciliation step.
- **Registry**: new `kind: "intraday_directional"` in `pdp/strategy/unified_registry.py` and
  `pdp/backtest/job_handlers.py`, so variants are registrable via `POST /api/v1/strategies/register`
  and launchable via `POST /runs` with no code change.

### Resolved ambiguities in the source spec

- **"VWAP (session)"** — the source doc itself asks "future or option price?". NIFTY spot (sid `13`)
  carries zero volume so `VWAPTracker` can never converge on it, and no futures history is ingested
  (`futures` coverage family is `unavailable`). An option's own VWAP is computable but comparing
  index spot to an option premium's VWAP is meaningless. Resolved as a session-anchored mean of
  typical price `(H+L+C)/3` on the spot 1m series, `vwap_source: "session_twap"`, with the
  ATM-option VWAP available as an optional additive gate (`atm_option_vwap_gate`, default off).
- **Exit rule 5, "premium rises by 1%"** — taken literally this fires on nearly every tick and no
  trade survives. Implemented as `premium_rise_stop_pct`, default `1.0` (= 100%, premium doubles).
- **Exit rules 5 vs 6** — rule 6 (20% unrealised loss on a short) *is* a 20% premium rise, so it
  always precedes rule 5. Both are knobs; rule 5 is a backstop when rule 6 is disabled.
- **ORB** — strictly the 15m candle stamped 09:15 (the 09:15–09:30 window). The existing strangle
  code accepts 09:15 *or* 09:30; this change does not copy that looseness.

## Impact

- **Affected specs**: new capability `intraday-directional-selling`.
- **Affected code**: 7 new modules + 1 new live YAML + 2 new backtest configs; edits confined to
  `pdp/strategy/unified_registry.py`, `pdp/backtest/job_handlers.py`, `pdp/strategy/atm_suite.py`
  (pure extraction), `pdp/strategies/directional_strangle.py` (delegates to the extracted
  `pdp/strategy/fills.py`; no behaviour change), `Taskfile.yml`,
  `.claude/skills/strategy-add/SKILL.md`.
- **`directional_strangle` is otherwise untouched** — it is a live strategy and destabilising it is
  not in scope.
- **Data caveat** (verified against `option_bars`, 2026-07-26): NIFTY carries a 763-day expiry
  blackout 2020-12-03 → 2023-01-05 (still present; `option-bars-expiry-gap-backfill` task 3.2 is
  deferred) plus 16 smaller 12–21 day cadence gaps. Clean NIFTY option history starts 2023-01-05.
  BANKNIFTY is clean 2021-08-05 onward and supplies the genuine 5-year read.
- **Default posture is paper.** Live orders remain gated on `LIVE=1` + `BROKER=dhan`; promotion to
  live is out of scope for this change.
