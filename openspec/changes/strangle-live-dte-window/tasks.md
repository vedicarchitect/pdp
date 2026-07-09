# Tasks — strangle-live-dte-window

## 1. Live strategy wiring
- [x] 1.1 `DirectionalStrangle.__init__`: `self._dte_max = int(p["dte_max"]) if p.get("dte_max") is not None else None`
- [x] 1.2 Import + use `within_dte` and the existing `nearest_weekly_expiry` in `on_bar`
- [x] 1.3 Resolve the current expiry for the underlying once per bar (cache within the bar)
- [x] 1.4 Before opening new legs, skip entry when `not within_dte(bar_day, expiry, self._dte_max)`
- [x] 1.5 Emit the bias/heartbeat event with a `dte_gated` reason when the gate blocks entry
- [x] 1.6 Ensure the gate does NOT affect stop management, rolls, or square-off of open legs

## 2. Config
- [x] 2.1 Set `dte_max: 15` in `backtest/configs/strangle_nifty_hedged.yaml`
- [x] 2.2 Set `dte_max: 15` in `backtest/configs/strangle_banknifty_hedged.yaml`
- [x] 2.3 Set `dte_max: 15` in `backtest/configs/strangle_sensex_hedged.yaml`

## 3. Tests + validation
- [x] 3.1 Unit: `within_dte` boundary — blocked past window, allowed inside/at expiry, `null` = no filter
      (`tests/instruments/test_within_dte.py`)
- [x] 3.2 Parity: live gate reuses the same `within_dte` helper as the backtest walk-forward
      (structural parity — single shared function)
- [x] 3.3 `task test` green
- [x] 3.4 `openspec validate --strict strangle-live-dte-window` passes
