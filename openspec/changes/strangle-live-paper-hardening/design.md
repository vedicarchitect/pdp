## Context

Root causes were traced from the 2026-06-29 paper logs (`/strangle-review`). Two are correctness
bugs that corrupted the run (R1 LTP path, R2 fabricated losses); three are quality gaps (R3 signals,
R4 hysteresis, R5 halt durability). This note records the non-obvious design decisions.

## Decisions

### R1 — dynamic subscription set on the host (not widening the YAML watchlist)
Option SIDs are discovered at runtime (strikes depend on spot + bias) so they cannot be enumerated in
the static YAML watchlist. The host therefore keeps a per-running-strategy dynamic set, unioned with
the static watchlist at dispatch time. This keeps the static watchlist as the declarative source for
indicators/warmup while letting tick delivery follow runtime subscriptions. The set is cleared on
unsubscribe and on stop to bound memory. Paper fills are unaffected (they already use Redis pub/sub).

### R2 — two independent defenses
A fill-timing race produced `avg_price = 0`, and the P&L formula turned that into a fake loss. We fix
**both** layers so neither alone can recur:
- **Fill side:** read the already-cached `ltp:<sid>` at order placement instead of waiting for the
  next pub/sub tick. A 0-priced fill is nonsensical, so the order stays pending rather than persisting
  a zero average.
- **Accounting side:** even if a zero average is somehow stored, `upsert_position` refuses to compute
  realized P&L against it. This guard alone would have prevented the −₹59k BANKNIFTY cap.
This guard is intentionally conservative (skip + warn) rather than guessing a price — a position with
no real entry price has no defensible realized P&L.

### R3 — VWAP from futures; PCR from the chain poller
An index spot has no traded volume, so spot VWAP is structurally null — we source the front-month
index **future** instead. PCR is derived from the existing option-chain poller's OI rather than a new
feed. `ema_1h`/`ema_15m` are already configured; the gap is warmup seeding (the 50-bar values dict is
not populated before the first bar), so the fix is in warmup, not the bias engine. `cam_weekly` needs
a genuine `1w` bar/pivot snapshot, which does not exist yet.

### R4 — confirmation counter, mirroring the premium-stop gate
The codebase already has a 3-bar gate for premium-stop re-entry; bucket hysteresis follows the same
shape (pending-bucket + counter, reset on revert). Default `bucket_confirm_bars = 2` — enough to kill
single-bar `ema_5m` chatter without materially lagging genuine regime shifts on 5m bars.

### R5 — persisted halt marker keyed by (strategy_id, IST day)
`_done_for_day` is in-memory and resets on restart. We persist a marker (Redis key via the existing
client is preferred — cheap, already wired, auto-expirable) read on startup and cleared on IST date
rollover, so a restart cannot bypass a real kill. Once R2 lands, genuine caps are rare, but a real
risk halt must never be silently undone by an ops restart.

## Risks / notes
- Paper-only change (`LIVE=0`); `backend/.env` is never read or written.
- `task reset-paper` is required post-merge to clear today's corrupted PG P&L before the next run.
- Sits on top of the merged `ops-safety-net` stack; no dependency on its feed-halt beyond coexistence.
