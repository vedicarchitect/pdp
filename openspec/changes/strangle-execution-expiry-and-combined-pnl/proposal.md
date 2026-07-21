# strangle-execution-expiry-and-combined-pnl

## Why

Live-verified 2026-07-20 during the go-live paper session, directly reported by the user viewing
the app:

1. **"I see old last week entries in SENSEX."** Confirmed real, not a bug: `DirectionalStrangle`
   correctly rehydrates open positions from the DB/broker on every restart
   (`strategy/recovery.py`) — the SENSEX legs the user is seeing are genuine open positions
   carried over from a prior session, not fresh entries. But the leg model
   (`OpenLeg`/`LegRow`) has no field the UI can use to tell "opened today" from "opened days
   ago and still running" — `entry_time` is `None` for a rehydrated leg (the in-memory dataclass
   was reconstructed, not freshly timestamped), and nothing surfaces the leg's **expiry** or
   **DTE**, even though `OpenLeg.expiry: date | None` is already resolved and stored at open
   time (`directional_strangle.py:135`, populated at `:1230`/`:1250`). The information exists
   server-side; it just never reaches `/monitor` or the Flutter execution screen.
2. **"I don't see BN."** Investigated live: not a bug — BANKNIFTY's `n_open_shorts`/
   `n_open_hedges` were genuinely `0` at the time because its most recent entry attempt hit
   `entry_aborted reason="fill_unresolved"` (the documented, correct behavior from
   `strangle-entry-fill-race-and-latch` — a cold-LTP entry is aborted rather than corrupting
   state, and retried on the next 5m bar). No fix needed here, but it sharpened the same
   underlying gap: the execution screen has no per-underlying "last attempt/last abort" signal
   either, so an empty BANKNIFTY group is visually indistinguishable from "strategy not running"
   or "genuinely broken."
3. **"Combined P&L line (for strategy) for each index."** Confirmed a real, separate gap while
   investigating: `backend/pdp/strategy/routes.py`'s per-underlying `groups[].totals.day_realized`
   is hardcoded to `0.0` with the comment `"per-index realized not tracked separately"`
   ([routes.py:847](../../../backend/pdp/strategy/routes.py#L847)) — even though `state()` already
   returns `day_realized`/`day_unrealized`/`day_pnl` per strategy instance
   ([routes.py:873-875](../../../backend/pdp/strategy/routes.py#L873-L875) sums exactly these
   fields from `states` for the overall total). The per-underlying data already exists in
   `states[i]`; the group-builder loop just never reads it.

This change also consolidates four smaller console/UI findings from the same 2026-07-20 live
session (per the approved plan), since they all touch the same leg-state/monitor/execution-tab
surface:

4. **`entry_reason` renders `"None@0.20"`** — `_reason = f"{self._current_bucket}@..."`
   ([directional_strangle.py:1220/:1360/:1476](../../../backend/pdp/strategies/directional_strangle.py#L1220))
   interpolates the literal `"None"` when the bucket isn't set yet. Cosmetic.
5. **Indicator Matrix right-edge truncation** — the matrix `DataTable`s already have an inner
   horizontal `SingleChildScrollView`, but the panel host is a fixed-width, non-flexing
   `SizedBox(width: clamp(440,720))`
   ([strategy_execution_tab.dart:104/:119](../../../app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart#L104))
   narrower than the 15-column table, and desktop shows no visible scrollbar → CamR4/CamS4 fall
   off-screen with no affordance.
6. **Rehydrated legs show `--` for LTP/P&L/day-range** — rehydration correctly re-subscribes
   and populates the leg, but `/monitor`'s LTP comes from the in-memory `self._ltp_cache`
   (advanced only in `on_tick`, [directional_strangle.py:750/:1988](../../../backend/pdp/strategies/directional_strangle.py#L1988)),
   which is empty right after restart until the next option tick lands. The cache is never
   seeded from a last-known price on rehydration.

## What Changes

- `/api/v1/strangle/monitor`: each leg in `groups[].legs[]` gains `expiry` (ISO date, from the
  already-resolved `OpenLeg.expiry`) and `dte` (calendar days from today to expiry, server-computed
  so the client never needs a date library for it). `state()` starts emitting `expiry`.
- `groups[].totals.day_realized` reads the real per-underlying value from `states[i]` instead of
  the hardcoded `0.0`; `day_pnl` recomputed as `day_realized + day_unrealized` per group to match.
- Flutter `LegRow` gains `expiry`/`dte` fields; the leg row widget renders DTE (e.g. "DTE 3") next
  to the strike/expiry, so a rehydrated multi-day-old position is visually distinguishable from a
  same-day entry without relying on `entryTime` (which is legitimately null for rehydrated legs).
- Flutter execution screen: each underlying's group header shows a combined realized+unrealized
  P&L line (mirroring the existing overall-totals line, scoped per underlying).
- **(Finding 4)** `entry_reason` guards the bucket value so it never renders the literal
  `"None"` (e.g. `self._current_bucket or "unknown"`).
- **(Finding 5)** The Indicator Matrix's horizontal overflow is made discoverable — a visible
  `Scrollbar` on the existing scroll view and/or letting the panel flex wider on large windows —
  so the rightmost columns are reachable.
- **(Finding 6)** `_ltp_cache` is seeded on rehydration from the last-known option price (Redis
  `ltp:<sid>` within TTL, else the position avg/last, else the last `option_bars` close) so a
  restored leg is priced immediately rather than showing `--` until the next tick.
- No change to rehydration correctness, entry-abort, or retry logic — those are confirmed working
  as designed; this change makes the resulting state legible in the UI and closes the cold-start
  pricing window.

## Impact

- Affected specs: `strategy-execution-monitor` — MODIFY the monitor-endpoint requirement (leg
  payload gains `expiry`/`dte`; per-group `totals.day_realized` is the real per-underlying value)
  and the Flutter Strategy Execution panel requirement (per-underlying combined P&L line, DTE
  display, discoverable indicator-matrix scroll, rehydrated-leg legibility).
- Affected code:
  - `backend/pdp/strategies/directional_strangle.py` — `state()` emits `expiry`;
    `_ltp_cache` seeded on rehydration; `entry_reason` bucket guard.
  - `backend/pdp/strategy/routes.py` — `strangle_monitor` computes `dte`, passes `expiry`
    through, and reads real per-group `day_realized` from `states[i]`.
  - `app/lib/features/manage/domain/execution_models.dart` — `LegRow` gains `expiry`/`dte`.
  - `app/lib/features/manage/presentation/` (tabs + `indicator_panel.dart`) — DTE render,
    per-group combined P&L line, visible matrix scrollbar/flex.
- No schema/migration changes — `expiry` is already persisted on `OpenLeg`/the leg DB row; this
  only adds it to an API response and a UI render.
