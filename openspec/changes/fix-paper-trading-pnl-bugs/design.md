## Context

The paper engine (`PaperBroker` + `upsert_position`) and the SuperTrend strategy have three independent bugs that compound to produce wildly wrong P&L numbers. Today's session showed Position.realized_pnl of -₹77,939 against a correct value of -₹11,693 — a 6× error driven entirely by the weighted-average sign bug. Separately, a cancelled entry SELL left an orphan long position worth -₹11,702 in phantom costs. The Perl monitor adds confusion by rendering the CANCELLED order as a `0.00!` row.

All three fixes are isolated, low-risk one- or two-liners. No schema migrations are needed. Existing positions rows for today are already corrupt; `reset_paper.py` cleans them.

## Goals / Non-Goals

**Goals:**
- Correct `upsert_position` so `avg_price` and `realized_pnl` are exact for multi-leg short positions.
- Prevent orphan BUY orders when an entry SELL is cancelled before a squareoff/flip event.
- Show only FILLED orders in the Perl blotter.

**Non-Goals:**
- Retroactive correction of today's position rows (use `reset_paper.py`).
- Refactoring `upsert_position` for long positions (already correct).
- Live-broker P&L (same `upsert_position` function is shared; fix benefits both, but this change is paper-only testing scope).

## Decisions

### D1 — Fix weighted average with `abs(old_qty)`

**Current**: `total_cost = old_avg * Decimal(str(old_qty)) + fill_price * Decimal(str(order.qty))`

For a short position, `old_qty` is negative, so `old_avg * old_qty` produces a negative cost, causing the average to flip sign with every additional leg.

**Fix**: `total_cost = old_avg * Decimal(str(abs(old_qty))) + fill_price * Decimal(str(order.qty))`

The `abs()` is a no-op for long positions (positive `old_qty`) so this is safe for all cases.

**Alternatives considered**: Rewrite using `abs` throughout the function. Rejected — the rest of the function already handles sign correctly via `Side.BUY/SELL` checks and the `old_qty < 0` branch.

---

### D2 — Guard `_current` assignment against terminal-state SELL

**Current**: `_open()` sets `_current` unconditionally after `_place()` returns an order. `_place()` only returns `None` on exception; a successfully-created-but-later-cancelled order is never `None`.

**Fix**: After `_place()`, check `order.status not in (CANCELLED, REJECTED, FILLED)` before setting `_current`. Since paper fills are synchronous on the next tick (not in the same call), a freshly placed MARKET order will always be `OPEN` at this point. The guard is a safety net for future edge cases.

**Why not wait for fill confirmation?** The strategy is event-driven on bar closes; we cannot block `on_bar` waiting for a tick. The check at placement time is sufficient.

---

### D3 — Cancel stale SELL in `_close_current()`

`_close_current()` places a BUY to close `_current["security_id"]`. If the original SELL never filled (still OPEN), the BUY fills against a zero-qty position, creating a phantom long. We must cancel the OPEN entry SELL before placing the BUY.

**Fix**: In `_close_current()`, before `_place(..., "BUY", ...)`: (1) call `ctx.orders.cancel_open_entry_orders(security_id)` — cancels all OPEN SELL orders for this security+strategy and removes them from the paper engine's in-memory watch list; (2) call `ctx.orders.get_net_qty(security_id)` — if net_qty == 0, skip the BUY and clear `_current`. The BUY qty is derived from `abs(net_qty) // lot_size` rather than `c["lots"]` so partial fills are handled correctly.

**Alternative**: Check position net_qty before placing BUY and skip if zero. Rejected — this silently drops the close without fixing the leak in the in-memory order list.

---

### D4 — Perl monitor FILLED-only filter

Add `&& ($_->{status}//'') eq 'FILLED'` to both the `@s_sell` and `@s_buy` grep predicates. CANCELLED and REJECTED orders have no trade record, so `$fill_px{$oid} = 0`, which appears as `0.00!`. Filtering them out removes the visual noise and the suppressed `--` P&L rows.

## Risks / Trade-offs

- **D3 cancel helper adds a DB write on every close event** — negligible for paper trading; one `UPDATE` per close.
- **`abs(old_qty)` fix makes today's accumulated position rows correct going forward but not retroactively** — existing corrupt rows must be reset.
- **D2 guard is defensive** — in normal operation the SELL is always OPEN at assignment time; the guard only fires on a race or external cancel.

## Migration Plan

1. Apply code fixes (tasks.md order).
2. Run `python reset_paper.py` to wipe corrupt position rows and reset sequences.
3. Restart the FastAPI server.
4. Restart `perl monitor.pl`.
5. Rollback: revert commits; re-run `reset_paper.py` (data is paper-only, no live impact).

## Open Questions

- Should `cancel_open_sells` be a method on `OrderRouter` (shared with live broker) or a private helper on `SuperTrendShort`? Leaning toward `OrderRouter` for reuse by other strategies.
