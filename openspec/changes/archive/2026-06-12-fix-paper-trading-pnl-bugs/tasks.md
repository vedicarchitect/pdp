## 1. Fix weighted-average for short positions

- [x] 1.1 In `src/pdp/orders/paper.py` `upsert_position()`, change `Decimal(str(old_qty))` to `Decimal(str(abs(old_qty)))` in the adding-to-position branch (line ~364)
- [x] 1.2 Verify the fully-closed path (`new_qty == 0`) still computes correct sign: `(fill_price - old_avg) * old_qty` is correct for shorts since `old_qty` is negative there (no change needed — confirm only)

## 2. Add `cancel_open_entry_orders` to OrderRouter

- [x] 2.1 In `src/pdp/orders/router.py`, add method `cancel_open_entry_orders(session, security_id, strategy_id)` that queries all OPEN SELL orders for the given security + strategy, sets each to CANCELLED with `cancelled_at = now()`, and calls `self._broker_for(broker).cancel_order(order_id)` for each
- [x] 2.2 In `src/pdp/orders/paper.py` `PaperBroker.cancel_order()`, confirm it removes the order from `_open_orders` in-memory list (already does — confirm only)

## 3. Guard `_current` and cancel stale SELL in strategy

- [x] 3.1 In `src/pdp/strategies/supertrend_short.py` `_open()`, after `_place()` returns an order, add guard: if `order.status` is CANCELLED or REJECTED, log a warning and return without setting `_current`
- [x] 3.2 In `src/pdp/strategies/supertrend_short.py` `_close_current()`, before `_place(..., "BUY", ...)`, call `await self.ctx.orders.cancel_open_entry_orders(c["security_id"], strategy_id=self.ctx.strategy_id)` to cancel any unfilled SELL for this leg
- [x] 3.3 Expose `cancel_open_entry_orders` via `StrategyContext.orders` (add the method to the orders context interface used by strategies)

## 4. Fix Perl monitor FILLED-only filter

- [x] 4.1 In `monitor.pl` around line 335, add `&& ($_->{status}//'') eq 'FILLED'` to the `@s_sell` grep predicate
- [x] 4.2 In `monitor.pl`, add the same `status eq 'FILLED'` filter to the `@s_buy` grep predicate

## 5. Reset and verify

- [x] 5.1 Run `python reset_paper.py` to wipe today's corrupt position rows and reset sequences
- [x] 5.2 Restart the FastAPI server and `perl monitor.pl`; confirm all blotter rows show FILLED entries only and no `0.00!` phantom rows
- [x] 5.3 Place a test 2-leg short manually via the API and verify `avg_price` is the correct weighted average and `realized_pnl` on close matches `(avg - close) * qty`
