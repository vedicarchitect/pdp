# strangle-live-dte-window

**Minimal context set** (load only these when working this change):
- `proposal.md`, `tasks.md`, `specs/strangle-live-dte-window/spec.md`
- Backend: `strategies/directional_strangle.py` (`__init__` param parse `:139`, `on_bar:294`,
  `nearest_weekly_expiry` import `:57`), `instruments/expiry_calendar.py` (`dte:37`,
  `within_dte:42` — reuse, do not re-implement), the three `backtest/configs/strangle_*_hedged.yaml`
- Reference: `backtest/strangle_config.py:129` (`dte_max`) + `strangle_walkforward.py:265-269`
  (how the backtest already applies `within_dte`) — mirror that decision live

**Scope:** lightweight, single-strategy behavioural change — wires an existing, backtest-honoured
config field (`dte_max`) into the live entry gate. No governance 5-phase (not infra/multi-service).
No new config key, no migration.

**Ship order:** independent — can land anytime; no dependency on the other five changes.
