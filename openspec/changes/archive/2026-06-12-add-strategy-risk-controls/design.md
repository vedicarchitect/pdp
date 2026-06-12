# Design — Strategy risk controls

## Context

`backtest_multiday.py` enforces (lines 39–40, 392–422):

```python
LEG_STOP_PER_LOT = 1_000.0   # close if MTM loss >= this × current lots
DAY_STOP_LOSS    = 10_000.0  # no more trades if realized day loss >= this
```

- **Leg stop** is checked at each bar's close, before flip/scale: if
  `mtm <= -(LEG_STOP_PER_LOT * lots)`, the leg is bought back at the bar-close price and the
  bar is skipped (`continue`) — **no new entry on the stop bar**.
- **Day stop** is checked after every close: if `day_pnl <= -DAY_STOP_LOSS`, `done=True` and no
  further trades occur that session.

The live strategy (`src/pdp/strategies/supertrend_short.py`) has neither.

## Decisions

### 1. Where the stop check lives

Add the evaluation at the **top of `on_bar`**, after the square-off / direction guards but
**before** the open/flip/scale branch — mirroring the backtest order:

```
on_bar:
  if past square-off: close + done
  if done_for_day: return
  read SuperTrend; if none: return
  --- NEW: day-stop guard ---
  if self._day_stop_hit: (already flat) return
  --- NEW: leg-stop check ---
  if open leg and unrealized_loss >= leg_stop_per_lot * lots:
      close_current("leg_stop"); return   # no re-entry this bar
  --- NEW: day-stop after realized update ---
  if day_realized_pnl <= -day_stop:
      close_current("day_stop"); self._day_stop_hit = True; return
  ... existing open/flip/scale ...
```

### 2. Sourcing the option's latest price (MTM)

The strategy needs the open leg's current option price to compute unrealized MTM. Options:

- **A. Redis `ltp:<sid>` hot cache** (chosen): the option feed is already subscribed on open
  (`_open` calls `ctx.market.subscribe`), so `ltp:<sid>` is populated. Read via a thin
  `ctx` accessor. Lowest latency, matches what `monitor.pl` reads.
- B. Track last tick in `on_tick` — adds state and a hot-path hook the strategy doesn't use today.
- C. Query the position's `unrealized_pnl` from PG — stale (only updated on fill).

Decision: **A**. Add a `ctx.market.ltp(security_id) -> float | None` read (or reuse an existing
LTP accessor if present) so the strategy stays paper/live agnostic. Unrealized MTM for a short:
`(avg_entry - ltp) * qty` (loss when ltp rises).

### 3. Average entry & quantity

Read avg entry and net qty from the ledger via `ctx.orders.get_position(security_id)` on each
leg-stop check (task 2.1 updated this decision). This is ledger-authoritative and handles
partial fills correctly — no extra state on `_current`. Unrealized MTM for a short:
`(avg - ltp) * abs(net_qty)` (negative when ltp > avg, i.e. a loss).

### 4. Realized day P&L tracking

Read realized P&L from the ledger via `ctx.orders.get_realized_pnl(security_id)` on each bar
(task 4.1 updated this decision). A per-security daily baseline (`_day_baseline`, captured at
first touch each IST day) is subtracted so only today's realized P&L counts toward the cap.
The accumulator resets on IST date rollover — the first bar of a new day clears `_day_baseline`
and `_touched`. Note: a stop-driven close lands in the ledger after the async cover fills, so
the day cap is caught at the start of the following bar, not the close bar itself.

### 5. Re-entry semantics

- **Leg stop** → close only; the *next* bar re-evaluates and may re-open per signal (matches
  `continue`).
- **Day stop** → close and latch `_day_stop_hit = True`; no entries until the next session.

## Risks / Trade-offs

- MTM from Redis LTP can briefly be `0`/stale before the first option tick; guard with the same
  `ltp <= 0` skip the paper engine already uses, so a stop never fires on a bogus zero price.
- Day-stop accumulator must reset per calendar day (IST). A long-running process across days
  must detect the date rollover; tie the reset to the first bar whose IST date differs.
