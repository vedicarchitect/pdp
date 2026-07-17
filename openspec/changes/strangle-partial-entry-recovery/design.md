# Design — strangle-partial-entry-recovery

## The failure, precisely

`_maybe_act_on_bucket` (the decision path, `directional_strangle.py:631-664`) opens legs **only** on a
confirmed bucket *transition*:

```python
pe_lots, ce_lots = self._ratio_for(result.bucket)          # :632
if self._current_bucket != bucket_str:                     # :634  transition branch
    ... hysteresis / confirm ...
    if self._pending_bucket_count >= self._bucket_confirm_bars:
        if self._short_legs or self._hedge_legs:
            await self._close_shorts_and_hedges("bucket_change")
        self._current_bucket = bucket_str
        if entry_allowed:
            await self._open_bucket(spot, pe_lots, ce_lots) # :655  one shot, never revisited
else:                                                       # :656  bucket unchanged
    self._pending_bucket = None                             #        -> does nothing about legs
    self._pending_bucket_count = 0
```

`_open_bucket` (`:968`) opens PE then CE via `_open_short`. `_open_short` (`:1019`) has several
silent-return abort paths; the one that bit us is the unresolved fill price
(`_resolve_fill_price` → `None` → `fill_avg_px_zero`, `:1064-1076`): the order is cancelled and the
leg is **not** recorded (correct — avoids `entry_price=0` phantom MTM). Nothing retries it, and the
`else` branch at `:656` never re-opens within a bucket. So one cold contract => a permanently lopsided
book until the bucket changes.

## The fix

Turn the no-op `else` branch into a **composition reconcile** for the current bucket, driven by
per-episode intent state.

### New per-episode state (reset on confirmed bucket change)

- `self._bucket_target: dict[str, int]` — intended short lots per side, `{"PE": pe_lots, "CE": ce_lots}`,
  set when a bucket is acted on.
- `self._bucket_realized: set[str]` — sides that have opened ≥1 short leg this episode. A side is added
  the moment `_open_short` registers a leg (`_add_leg` succeeds).
- `self._recovery_attempts: dict[str, int]` — per-side attempt counter for the episode.

Reset all three wherever `self._current_bucket` is assigned on a confirmed change (`:651`).

### Reconcile pass (runs on the bucket-unchanged path, and after the initial open)

```
for side in ("PE", "CE"):
    target = self._bucket_target.get(side, 0)
    if target <= 0:                      continue   # bucket doesn't want this side
    if self._open_short_lots(side) > 0:  continue   # already have it
    if side in self._bucket_realized:    continue   # opened then exited (TP/roll) — don't resurrect
    if side in self._stop_gate:          continue   # deliberately gated by a stop
    if self._recovery_attempts[side] >= max_attempts:
        emit ENTRY_SIDE_UNFILLED(side); continue
    self._recovery_attempts[side] += 1
    emit ENTRY_RECOVERY_ATTEMPT(side, attempt=n)
    await self._open_short(spot, side, target)      # normal path: lock, cap, hedge
```

Gate the whole pass behind the same `entry_allowed` used for the initial open, `not
self._done_for_day`, `not (neutral and self._neutral_no_trade)`, `not self._lot_size_degraded`, and a
new `self._entry_recovery_enabled` flag. `_open_short_lots(side)` sums `leg.lots` over open short legs
of that `opt_type`.

The **initial** `_open_bucket` and the **recovery** pass share the same reconcile: after
`_open_bucket` runs on a bucket change, run the reconcile once more that same bar so a same-bar abort
is already counted; thereafter the unchanged-bucket path reconciles every bar. Realized-marking makes
this idempotent — a side present or already-realized is skipped.

### Why realized-set + stop-gate is enough to avoid resurrection

- **Take-profit** closes a side to bank credit; the side is in `_bucket_realized`, so reconcile skips
  it. (It stays skipped for the rest of the episode — intended: TP is a deliberate exit.)
- **Stop** puts the side in `_stop_gate`; reconcile skips it, and the existing stop-recovery cooldown
  owns any re-entry.
- **Roll** manages an existing leg; the side keeps an open leg (or is transiently handled under its own
  lock), so `_open_short_lots(side) > 0` and/or realized skips it.
- **Never opened (abort)** — the only case left — is exactly what we recover.

### Config

Add to `StrategyConfig` (and the three `strangle_*_hedged.yaml` are untouched — defaults apply):

- `entry_recovery_enabled: bool = True`
- `entry_recovery_max_attempts: int = 3`

### Events

- `ENTRY_RECOVERY_ATTEMPT` (info) — side, attempt number, target lots.
- `ENTRY_SIDE_UNFILLED` (warning, terminal) — side, attempts, reason, so the lopsided book is
  visible in the event feed / OpenSearch rather than only inferable from `leg_open` gaps.

## Out of scope

- Topping up a **partially** filled side (some lots opened, fewer than target). Recovery targets
  sides with **zero** open legs — the observed and highest-risk case — to avoid churn near the lot
  cap. Can be a follow-up if partial fills prove common.
- A pre-entry feed-freshness gate. The reconcile makes entries self-correct regardless of *why* a
  side failed, which is more robust than trying to predict a cold contract; no new gate is added.
- Backtest simulator — fills are deterministic there; no change.

## Test seams

`_open_short` is already fully faked in `tests/strategies/` (fake broker + `session_maker`). Tests
force `_resolve_fill_price`/fake-broker to return a zero/None avg-px for a chosen side, drive
`on_bar` across bars, and assert recovery behavior. No live Dhan, paper-only.
