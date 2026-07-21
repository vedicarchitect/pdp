# bar-warmup-reconcile-from-1m

## Why

On 2026-07-19 live diagnosis (markets closed) found NIFTY's app indicators frozen at a stale
bearish state (EMA9=24093 vs Kite 24305, RSI 44 vs 72) despite a **pristine 1-minute series**
in `market_bars` (926k docs, full 375-bar sessions through Jul 17). The higher-timeframe stores
the engine actually seeds from were corrupt in two distinct ways:

- **Duplicates**: Jul 14 15m held 50 bars instead of 25 (a flush/late-tick race — see
  `pdp/market/bars.py`'s `flush_session` resetting `_bar_time`, then a delayed tick reopening the
  just-flushed bucket).
- **Gaps**: Jul 17 15m held 0 bars for the session (the feed died mid-session and the in-memory
  higher-TF bucket, which only persists on the next boundary tick or the 15:30 flush, was lost on
  restart).

`scripts/oneoff/rebuild_market_bars.py` (delete-then-insert derive-from-1m) fixed both by hand this
session, and `warmup.py` already has equivalent machinery
(`_derive_bars_from_1m`/`_replace_derived_bars`, landed in `indicator-warmup-derive-from-1m`) — but
it **only runs when `len(bars) < target_bars`** (`warmup.py:270`). That guard catches gaps (too few
bars) but not duplicates (too many bars): Jul 14's 50-bar 15m store passes the depth check untouched,
so a duplicate/misaligned store silently seeds the tracker every single restart, indefinitely, with
no log line indicating anything is wrong.

The user's ask is explicit: make the fix **persistent and auto-healing across any restart pattern**
— short outages, a multi-hour gap, or a fresh boot after not running for days — with all prechecks
done automatically at start, not as a one-off manual script run.

## What Changes

- **Warmup reconciles derivable timeframes (15m/30m/1H) from 1m unconditionally**, not only on
  depth shortfall. Before seeding, compare the stored higher-TF bars against a 1m-derived rollup
  for the same window (session-anchored, via the existing `_bar_boundary`/`_derive_bars_from_1m`):
  if the stored series has extra bars at a boundary (duplicates), a missing boundary the 1m data
  covers (a gap), or an OHLCV mismatch at a shared boundary (misalignment), replace the stored
  window with the 1m-derived one before seeding. When stored and derived already agree, skip the
  write (idempotent — no-op on a healthy store).
- **Log a distinguishable event** (`indicator_warmup_reconciled_from_1m`) with the duplicate/gap
  counts found, separate from the existing `indicator_warmup_derived_from_1m` (depth top-up) so
  boot logs make clear *why* a rewrite happened.
- **Bound the reconciliation window** to what warmup already fetches (`since` = the same lookback
  window used for depth), so this stays a cheap boot-time check (single Mongo read of 1m + higher
  TF over the existing warmup window) — no new full-history scan.
- **No change to `BarAggregator` itself.** The live aggregator's flush/duplicate race is a separate,
  lower-priority hardening item (self-heal mid-session without a restart); this change makes the
  *boot-time* path — which runs on every restart regardless of cause — the durable guarantee the
  user asked for. A running engine that never restarts still depends on the live aggregator being
  healthy; restarting periodically (or after any outage) now always produces a clean re-seed.

## Impact

- Affected specs: `indicator-warmup` (reconciliation, not just top-up, is now in scope for
  derivable timeframes).
- Affected code: `backend/pdp/indicators/warmup.py` — `_warm_one` gains an unconditional
  reconcile-from-1m step for `_DERIVABLE_TF_MINUTES` timeframes, ahead of the existing depth-check
  branch; new `_bars_disagree(stored, derived) -> bool` helper (duplicate/gap/mismatch detection at
  the bucket level).
- No schema/migration changes; `_replace_derived_bars` (delete-then-insert) is reused as-is.
- Depends on `indicator-warmup-derive-from-1m` (adds `_derive_bars_from_1m`,
  `_replace_derived_bars`, `_DERIVABLE_TF_MINUTES`) already being on this branch — confirmed
  present in `warmup.py`.
