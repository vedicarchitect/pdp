# strangle-reconcile-latch-clears

## Why

Live-verified 2026-07-20 (Dhan token refreshed, markets open, all three strangles trading):
NIFTY readiness became permanently `blocked` on
`Reconciliation: "2 leg(s) diverged"` while every other component stayed `ok`. This blocks
NIFTY from opening any **new** legs for the rest of the session (existing legs continue to be
managed/closed normally). Confirmed via
`GET /api/v1/strangle/readiness?strategy_id=directional_strangle_nifty` that the block
appeared shortly after NIFTY's 4 legs opened at 11:05 IST, did **not** self-heal across
repeated rechecks, and that all 4 legs subsequently showed the correct 6 lots each — i.e. the
underlying memory-vs-broker mismatch had already healed, but the readiness gate stayed stuck.

Root cause: `DirectionalStrangle._reconcile_divergences`
([directional_strangle.py:1949-1967](../../../backend/pdp/strategies/directional_strangle.py#L1949-L1967))
runs on every `state()` poll ([:1983](../../../backend/pdp/strategies/directional_strangle.py#L1983))
and calls `_flag_divergence` whenever an in-memory `leg.lots` disagrees with the broker's
`net_qty` (from the PostgreSQL `positions` table via
[`get_positions`, context.py:366-375](../../../backend/pdp/strategy/context.py#L366-L375)).
`_flag_divergence` only ever **adds** to `self._divergences`
([:1934](../../../backend/pdp/strategies/directional_strangle.py#L1934)); nothing anywhere
removes/discards/clears it (grep-confirmed: no `_divergences.discard/.remove/.clear`, no
reassignment). The readiness Reconciliation component blocks whenever
`len(self._divergences) > 0`
([:428-433](../../../backend/pdp/strategies/directional_strangle.py#L428-L433)).

So a **transient** mismatch — most plausibly a fill-timing race where the `positions` row lags
the in-memory `leg.lots` by a poll or two right after entry (the 2-of-4 legs that happened to
be mid-fill when a `state()` poll ran) — latches the readiness gate for the entire session
even after the DB catches up. The mismatch detection is correct; the missing behavior is
letting the flag **clear** once the mismatch is gone.

## What Changes

- `_reconcile_divergences` **recomputes** the divergence set each pass instead of monotonically
  accumulating: it builds a fresh set of currently-diverged sids from the current
  memory-vs-broker comparison and assigns it to `self._divergences` at the end of the pass. A
  mismatch that has healed is therefore absent from the new set, so the readiness Reconciliation
  component returns to `ok` on the next poll.
- `self._divergence_shapes` (the per-`(sid, mem, broker)` alert-rate-limiter) is **retained
  across passes** — a genuinely persistent mismatch still emits `LEG_STATE_DIVERGED` only once
  per distinct shape per session, so this change does not reintroduce alert-storming. Only the
  readiness gate reflects current truth; the alert cadence is unchanged.
- No change to how a mismatch is *detected*, to how legs are closed on real divergence, or to
  the "close only the smaller of memory/broker" safety rule — this is purely about the readiness
  gate self-healing when the mismatch is transient.

## Impact

- Affected specs: `strangle-observability-gaps` (adds a self-clearing scenario to the existing
  readiness/reconciliation requirement).
- Affected code: `backend/pdp/strategies/directional_strangle.py`
  (`_flag_divergence`/`_reconcile_divergences`, and the internal comment on `_divergences`).
- No schema/migration changes. No change to backtest (reconciliation is a live/paper-only,
  broker-mirror concern; backtest fakes lacking `get_positions` are already skipped).
- Risk: low — the fix makes the gate *less* sticky, never *more*; a real persistent mismatch
  still blocks and still alerts.
