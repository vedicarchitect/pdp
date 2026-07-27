# eod-walkthrough-report

## Why

The only artifact that has ever let anyone read a trading day end-to-end and spot real bugs was a
hand-written file, `backend/backtest/manual/2026-07-21_to_24_lastweek_walkthrough.md`, produced by
an ad-hoc script that no longer exists. It was unreproducible, omitted NIFTY spot next to every
fill, and — as the audit that prompted this change showed — its own numbers were wrong.

That audit surfaced two defects that had to be fixed *before* any generator is built on top of
them, otherwise every future report encodes the same lie:

1. **`strangle_sim.close_partial_leg` doubled the remaining leg's entry price.** It wrote
   `leg.total_qty = remaining * lot` and then read `leg.avg_entry` (a derived property,
   `total_cost / total_qty`) to rewrite `total_cost` — qty halved, cost didn't, entry price
   doubled. On 2026-07-21 this inflated a PE remainder's take-profit from ~+400 to +10,316 and
   fired a TP that should not have fired; the true day-loss halt trips one exit earlier. Live was
   never affected (`directional_strangle._partial_close` decrements `leg.lots` without touching
   `entry_price`) — this was a backtest-only divergence, which is exactly why it survived.
2. **The VIX gate was not single-sourced.** `bias._vix_gate` had no on/off switch; it only allowed
   when `vix_now is None`, and every caller faked that condition independently. Three entry points
   (`strangle_walkforward.py`, `sweep_engine.py`, `replay.py`) never got the memo and gated even
   against a `vix_gate_enabled: false` config — silently scoring a worse strategy on those
   surfaces, since the gate costs ~₹33L and increases MaxDD per `memory/directional_strangle.md`.
   This is also why the original walkthrough claimed 2026-07-22 traded zero times "VIX gate stayed
   shut" — the gate was active on that surface despite the config saying otherwise.

**Intended outcome:** a `task eod:walkthrough` runnable after every close — or against any past
date or range — that writes one markdown file per trading day into
`backend/backtest/manual/YYYY-MM-DD.md`, covering both strategies with per-minute spot/indicator/
leg detail, every order with NIFTY spot beside it, every decision with its reason, and a ranked
FINDINGS list from automated invariant checks so bugs can be worked one at a time and the file
re-generated to confirm the fix.

## What Changes

- **Fix `close_partial_leg`'s entry-price doubling** (`pdp/backtest/strangle_sim.py`): snapshot
  `avg_entry` before mutating `total_qty`; add the day-loss-cap check a partial close was missing;
  add a `half_stopped` one-shot latch mirroring live's `OpenLeg.half_stopped`.
- **Single-source the VIX gate**: `BiasWeights.vix_gate_enabled` (`pdp/signals/bias.py`) is the one
  switch `_vix_gate` reads; remove the independent null-out/skip-load workarounds in
  `strangle_run.py` and `directional_strangle.py`; move the YAML knob from `StrangleConfig`
  top-level into its `weights:` block (with a one-release deprecation shim); fix
  `weights_from_params` to map every `BiasWeights` field generically instead of a hardcoded subset.
- **Widen both engines' per-bar traces** (`BarStatus`/`StrangleDayData` in `strangle_sim.py`,
  `IntradayBarStatus` in `intraday_sim.py`) to carry the full bias/entry inputs and results that
  were already computed but previously discarded, plus a 1-minute spot ribbon — without changing
  either engine's decision cadence.
- **New pure renderer** `pdp/backtest/walkthrough.py`: `render_day()` takes already-replayed
  results and returns a markdown string (header, verdict, per-strategy timeline/fills/closed-legs/
  why-no-trade census/decision-bar table/minute ribbon, cross-strategy contrast, optional live
  overlay, FINDINGS). No I/O; unit-testable against synthetic days.
- **New findings engine** `pdp/backtest/walkthrough_checks.py`: rule-based detectors over
  `(trace, decisions, trades, legs, config)`, each emitting `Finding(id, severity, title, evidence,
  bar_refs)` — generic invariant checks (P&L reconciliation, cost/qty consistency, halt breaches,
  TP math, straddle collapse, stale bars, quorum, VIX-gate regression guard, data gaps) rather than
  one-off checks tied to a single day's numbers.
- **New runner** `backend/backtest/walkthrough_run.py`: replays both engines over a requested
  window and writes one file per trading day plus an `INDEX.md` summary row. Accepts `--date`,
  `--from/--to`, `--days/--start`, defaulting to today only when nothing is passed — any historical
  date works identically. Refuses non-trading days and the confirmed NIFTY 763-day blackout
  (2020-12-03 → 2023-01-05) without `--force`; surfaces `cadence_gap_days` as a loud banner and a
  finding rather than silently reporting over mismatched-contract data.
- **New task + skill**: `task eod:walkthrough` (Taskfile) and `.claude/skills/eod-walkthrough/
  SKILL.md` (`/eod:walkthrough [date|range]`).
- Regenerate 2026-07-21 → 2026-07-24 with the corrected engine, replacing the hand-written file.

**Deliberately out of scope** (each is a further behaviour change needing its own validation, and
the promoted NIFTY/BANKNIFTY/SENSEX baselines are all overstated by the partial-close fix —
re-baselining is a separate call):
- restoring `leg_buckets` after a roll (silently kills TP on rolled legs under
  `take_profit_extreme_only: true`)
- backtest/live take-profit formula parity
- square-off price source (`db.open` → close)
- neutral-bucket straddle / roll-target / opposite-side-cooloff policy
- re-running the promoted three-index baselines after the partial-close fix

## Impact

- **Affected specs**: new capability `eod-walkthrough-report`; corrects behaviour of the existing
  `directional-strangle` capability's backtest engine (partial-close arithmetic, VIX gate config
  surface) without changing its live behaviour or its spec'd requirements.
- **Affected code**: `pdp/backtest/strangle_sim.py`, `pdp/signals/bias.py`,
  `pdp/backtest/strangle_config.py`, `pdp/strategies/directional_strangle.py`,
  `backtest/strangle_run.py`, `pdp/backtest/intraday_sim.py`, `Taskfile.yml`.
- **New files**: `pdp/backtest/walkthrough.py`, `pdp/backtest/walkthrough_checks.py`,
  `backtest/walkthrough_run.py`, `.claude/skills/eod-walkthrough/SKILL.md`, plus tests.
- **No re-baseline is bundled.** The partial-close fix changes backtest-only P&L for any run that
  ever half-closed a leg; the promoted configs are not re-run as part of this change.
