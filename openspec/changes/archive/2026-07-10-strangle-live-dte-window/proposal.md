# strangle-live-dte-window

## Why

We want the directional strangle to **enter only in the last N days before expiry** (default 15) —
where theta decay is steepest and the bias edge is strongest — rather than opening new legs early
in the expiry cycle.

The config field for this **already exists and is honoured in the backtest**: `dte_max`
(`backtest/strangle_config.py:129`), applied through the shared calendar helper
`within_dte(trade_date, expiry, dte_max)` (`instruments/expiry_calendar.py:42`) in the walk-forward
and sim, and exposed in `unified_registry.py`. But the **live** `DirectionalStrangle` strategy
never reads `dte_max` — so the field is dormant in paper/live and the strategy currently opens legs
regardless of days-to-expiry. This closes that live/backtest gap by wiring the *existing* field
into the live entry gate (no new config concept, no hardcoded weekday — expiry is resolved
dynamically, per [[no_hardcoded_expiry_weekdays]]).

## What Changes

- **Live strategy reads `dte_max`.** `DirectionalStrangle.__init__` parses `self._dte_max` from
  params (default unchanged: `None` = no filter).
- **Entry gate by DTE.** In `on_bar`, before opening any new leg, the strategy resolves the current
  weekly expiry for its underlying and skips new-leg entry when
  `within_dte(bar_day, expiry, self._dte_max)` is `False` — reusing the *same* helper the backtest
  uses, so live and backtest agree exactly. Existing open legs continue to be managed (stops,
  rolls, square-off) — the gate blocks **new entries only**.
- **Set the window to 15 days.** Set `dte_max: 15` in the three live strangle configs
  (`strangle_nifty_hedged.yaml`, `strangle_banknifty_hedged.yaml`, `strangle_sensex_hedged.yaml`),
  replacing the current `null`.
- **Emit a skip event.** When entry is gated by DTE, emit the existing bias/heartbeat event with a
  `dte_gated` reason so the console/logs show *why* no legs opened (no silent no-op).

## Impact

- **Affected specs:** `strangle-live-dte-window` (new — live DTE entry gate). No change to the
  backtest DTE semantics (already correct); this brings live to parity.
- **Affected code:** `strategies/directional_strangle.py` (parse `dte_max`, DTE entry gate in
  `on_bar`), the three `backtest/configs/strangle_*_hedged.yaml` (`dte_max: 15`). Reuses
  `instruments/expiry_calendar.within_dte` + `nearest_weekly_expiry` (already imported).
- **Reuses:** the existing `dte_max` field, `within_dte()` helper, and the strategy's existing
  expiry resolution — no new dependency, no new config key, no migration.
- **Parity:** after this, a live day and a backtest of the same window apply the identical DTE
  filter; ties into [[live_backtest_parity]].
