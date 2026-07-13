# Tasks — lot-size-live-reconciliation

## 1. Tests first (they fail on today's code)
- [x] 1.1 `tests/instruments/test_lot_size_lookup.py`: new helper returns the `lot_size` of any
      resolvable option row for an underlying; returns `None` when the `instruments` table has no
      matching rows
- [x] 1.2 `tests/strategies/test_directional_strangle_lot_size.py`: strategy resolves
      `self._lot_size` from the instruments table at session start, not from YAML
- [x] 1.3 YAML `lot_size` present + mismatched vs. resolved value → warning logged, resolved value
      used for sizing (not the YAML value)
- [x] 1.4 YAML `lot_size` absent → resolves and uses scrip-master value silently
- [x] 1.5 Empty `instruments` table for the underlying → new entries blocked, degraded state
      surfaced, no hardcoded fallback used
- [x] 1.6 Existing open legs still price/close correctly using last-known-good lot size while
      new-entry trading is degraded
- [x] 1.7 Lot size resolved once per trading day — no repeated DB query across bars within the same
      day (asserted via call-count spy on the lookup)
- [x] 1.8 Lot size changes between two simulated trading days (same process, no restart) → second
      day picks up the new value

## 2. Instruments-table lookup helper
- [x] 2.1 Added `lot_size_for_underlying(session, underlying) -> int | None` in `pdp/strategy/strikes.py`
      (alongside the sibling `resolve_otm_option`/`nearest_expiry` instruments-table helpers) —
      queries `Instrument.lot_size`, ordered by nearest expiry first, `scalar_one_or_none()`
- [x] 2.2 Called only from `_maybe_resolve_lot_size`, itself gated to once per IST trading day — not
      wired into any per-bar/per-tick hot path

## 3. Strategy integration
- [x] 3.1 `DirectionalStrangle.__init__`: `self._lot_size` still seeds from YAML (or the 65 default)
      for the very first bar before resolution runs; `_maybe_resolve_lot_size` then overrides it
      every trading day, per-underlying cache via `self._lot_size_day: date | None`
- [x] 3.2 Session-start hook: `_maybe_resolve_lot_size(bar_day)` called from `on_bar` right after
      `_maybe_reset_day(bar_day)` — reuses the existing day-boundary detection, resolves once per
      `bar_day` (any timeframe's bar close triggers it; the day-key guard makes repeats a no-op)
- [x] 3.3 YAML `lot_size`, if present (`self._lot_size_yaml`), compared against resolved value on
      every resolution — `ctx.log.warning("lot_size_yaml_mismatch", ...)` on mismatch, resolved
      value always wins
- [x] 3.4 Degraded state (`self._lot_size_degraded`): resolution returning `None` blocks
      `_open_short`/`_open_hedge`/`_open_momentum` outright, emits one `EventType.INDICATOR_UNSEEDED`
      critical event, keeps `self._lot_size` at its last-known-good value for exit/MTM math
- [x] 3.5 Recovery: the next bar's resolution succeeding clears `_lot_size_degraded` and updates
      `self._lot_size` automatically — no restart needed

## 4. Config cleanup
- [x] 4.1 `strategies/directional_strangle_nifty.yaml`, `_banknifty.yaml`, `_sensex.yaml`: `lot_size`
      comments now state "advisory only — instruments table is authoritative at session start"
- [x] 4.2 Confirmed: `pdp/backtest/*` has its own separate, out-of-scope lot-size handling and never
      reads these live `strategies/*.yaml` files; no other live code path treats them as authoritative

## 5. Docs + validation
- [x] 5.1 `backend/pdp/strategy/CLAUDE.md`: documented the session-start lot-size resolution pattern,
      the YAML-is-advisory-only rule, and the degraded-state contract
- [x] 5.2 `task test` green (1120 passed); `pyright` on touched files shows only pre-existing debt
      unrelated to this change (`_stop_gate`/`_activity` loose dict typing, `routes.py`'s pre-existing
      `strangle_monitor` Unknown-type propagation) — the readiness/lot-size code itself introduces no
      new pyright errors (added a `TYPE_CHECKING` import for `StrategyReadiness` to fix a
      pre-existing unresolved-forward-ref issue in `check_readiness`'s return type)
- [x] 5.3 `openspec validate --strict lot-size-live-reconciliation` — done 2026-07-13, passes
