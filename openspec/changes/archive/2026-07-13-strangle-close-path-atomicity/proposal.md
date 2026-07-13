# strangle-close-path-atomicity

## Why

On 2026-07-09 live paper trading, strangle legs grew instead of closing. NIFTY sid 63993 went
18 → 4,608 lots over eleven roll retries; SENSEX sid 822316 went 12 → 12,288; BANKNIFTY showed the
same doubling across five securities with **no roll event in the log at all** (SENSEX sid 821960:
33 → 528 on ordinary `bucket_change`/`take_profit` closes). Day P&L reached six and seven figures of
pure fiction, and a phantom `-2.3L` tripped the BANKNIFTY day-loss cap.

An earlier fix (`f045282`) capped the **open** path with `_reserve_leg_lots` and a per-sid
`asyncio.Lock`. The growth continued, because the defects are on the **close** path, which that
change did not touch. Reading `backend/pdp/strategies/directional_strangle.py` end-to-end surfaces
four, three of which are provable from source alone.

**1. `_roll_leg` closes before it checks whether it can reopen.** (`:1181-1202`)

```python
try:
    await self._close_short_leg(leg, "roll")     # :1189  — the leg is now closed, for real
    await self._close_matching_hedge(leg)        # :1190
    spot = self._last_spot
    if spot is None or self.ctx.session_maker is None:   # :1193
        self._emit_event(..., result="skipped_no_spot")  # :1200
        return                                            # :1202 — reopen silently skipped
```

The same shape repeats at `:1214` (`no_instrument`) and `:1231` (`skipped_low_prem`). Every one of
these three "skip" branches has already closed the short **and its protective hedge**. The strategy
believes it rolled; it actually went flat and unhedged. The precondition checks belong *before* the
close, not after it.

**2. The roll guard is a check-then-act race.** The guard reads
`if ltp < self._roll_trigger_prem and leg.security_id not in self._rolling` at `:519`, but
`self._rolling.add(sid)` happens inside `_roll_leg` at `:1184` — after the caller's check has already
passed. Two ticks arriving close together both pass the guard and each run a full close-then-reopen.
Live evidence: SENSEX hedge sid 821946 rolled once cleanly, then was reopened by **two BUY orders
3 ms apart**, each for the full lot size, taking it to 16 lots over the 10-lot cap. The open-side cap
did not save it because each call's `get_net_qty` read raced ahead of the other's fill being
persisted, so both saw `existing_lots ≈ 0`.

**3. The close path closes the whole broker position but removes one leg object.** `_close_short_leg`
computes `close_lots = abs(net_qty) // self._lot_size` (`:1357`) from the **broker's net quantity for
the security**, then removes the leg by object identity: `[l for l in self._short_legs if l is not
leg]` (`:1384`). These two disagree whenever more than one `OpenLeg` shares a `security_id` — which
is exactly what a re-entrant roll or a same-strike reopen produces. One close flattens the broker
position for both legs; only one leg leaves the list. The survivor holds stale `lots`, is still
iterated by `on_tick` (`:505`, `:512`), and its next close reads `net_qty` for a position that was
already flattened.

**4. The close path takes no lock; the open path does.** `_open_short`/`_open_hedge`/`_open_momentum`
hold `_lock_for(sid)` across their check-then-place. `_close_short_leg` (`:1326`),
`_close_hedge_leg` (`:1386`) and `_close_momentum_leg` (`:1129`) read `get_net_qty` at `:1353` and
place the closing order at `:1378` with nothing held. A concurrent open on the same sid interleaves
freely between those two lines. Guarding one side of a read-modify-write and not the other provides
no mutual exclusion at all.

Finally, an observed failure whose mechanism is **not** established: after the duplicate-open race,
the resulting `OpenLeg` objects vanished from `state()`'s
`_short_legs + _hedge_legs + _momentum_legs` while the broker position stayed open at 16 lots in
Postgres. `_close_all` (`:1299`) iterates those same lists, so square-off would not have found the
position. Only a backend restart, which re-ran `_rehydrate_legs`, re-adopted and flattened it. This
is the most dangerous item here — it silently defeats square-off — and it must be reproduced under
test before any fix is written, not patched from a hypothesis.

The existing `POSITION_SIZE_CAPPED` alert at `:1366-1376` is a *safety net* for a misclassified leg
(it derives the closing side from the broker's net-qty sign). It is worth keeping, but it treats a
symptom of `strangle-leg-state-durability`, not the atomicity defects above.

## What Changes

- **Check preconditions before closing.** `_roll_leg` resolves `spot`, the new instrument, and the
  new leg's premium **first**. Only when a reopen is fully determined does it close the old short and
  its hedge. If any precondition fails, it emits `ROLLED result=skipped_*` and returns having changed
  nothing. Rolling becomes all-or-nothing.

- **Make the roll guard atomic.** The `sid in self._rolling` check and the `add` become a single
  guarded step under `_lock_for(sid)`, held across the guard itself rather than acquired inside
  `_roll_leg`. A second tick for the same sid finds the flag set and returns without acting.

- **Hold the per-sid lock across every close.** `_close_short_leg`, `_close_hedge_leg` and
  `_close_momentum_leg` acquire `_lock_for(sid)` around the `get_net_qty` → `_place` sequence, the
  same lock the open path uses. Read-modify-write on a security's position becomes serialised on both
  sides.

- **Make one leg the owner of one security.** A close reduces the broker position by *that leg's*
  lots, not by the whole `net_qty`, and legs are removed by security-id-and-identity together. Adding
  a second `OpenLeg` for a `security_id` that already has one is an invariant violation: it raises and
  emits a critical event rather than silently double-tracking.

- **Reproduce the vanishing leg before fixing it.** A test drives two concurrent rolls on one sid
  through the real `_rolling`/`_lock_for` machinery and asserts that the union of
  `_short_legs + _hedge_legs + _momentum_legs` accounts for the full broker `net_qty` at every step.
  Only once that test fails on today's code does a fix land. `state()` additionally asserts the
  invariant on every call and emits `LEG_STATE_DIVERGED` when in-memory lots and broker net-qty
  disagree.

- **Square-off stops trusting the in-memory lists.** `_close_all` reconciles against the broker's
  actual open positions for the strategy's securities and closes anything the lists do not know
  about, emitting a critical event for each orphan. Square-off is the last line of defence; it must
  not be able to miss a position because an in-memory list lost an object.

## Impact

- **Affected specs:** `strangle-close-path-atomicity` (new). Amends
  `openspec/specs/strategy-registry/spec.md`.
- **Affected code:** `backend/pdp/strategies/directional_strangle.py` — `on_tick:505-560`,
  `_roll_leg:1181-1257`, `_close_momentum_leg:1129`, `_close_all:1299`, `_close_short_leg:1326`,
  `_close_hedge_leg:1386`, `_close_matching_hedge:1438`, `state:1447`.
- **Highest priority of the strategy fixes.** Item 1 (`skipped_no_spot`) is the single largest source
  of the 2026-07-09 damage, and it also leaves the book **unhedged** — the hedge is closed at `:1190`
  before the skip returns. That risk is not captured by the P&L numbers.
- **Depends on `dev-reload-scoping`.** Diagnosing this by editing strategy code during a session
  currently restarts the backend and re-triggers the rehydration bug, muddying every observation.
- **Runs alongside `strangle-leg-state-durability`.** They are distinct: this change makes the close
  path atomic and correct for a *correctly classified* leg; that change makes the classification
  survive a restart. Both are needed. Ties into [[leg_rehydration_misclassification_bug]] and
  [[position_size_cap_and_lock_race]].
- **Paper-first.** No live orders until a full paper session shows zero `LEG_STATE_DIVERGED` events
  and a broker-vs-memory reconciliation clean at square-off.
