## MODIFIED Requirements

### Requirement: Positions accounting
The system SHALL maintain a `positions` row per `(security_id, exchange_segment, product)` updated on every fill using weighted-average pricing for additions and realize-on-reduce semantics. For short positions (net_qty < 0), the weighted average SHALL use the absolute value of the existing quantity: `total_cost = old_avg * abs(old_qty) + fill_price * order_qty`, divided by `abs(new_qty)`. The sign of `realized_pnl` on a short close SHALL be `(old_avg - close_price) * reduce_qty`.

#### Scenario: Add and reduce (long)
- **WHEN** BUY 50 @ 100 then BUY 50 @ 110 then SELL 50 @ 120 trades complete
- **THEN** the position has `net_qty = 50`, `avg_price = 105`, `realized_pnl = (120-105)*50 = 750`

#### Scenario: Add and reduce (short)
- **WHEN** SELL 130 @ 86.13 then SELL 65 @ 83.63 then BUY 195 @ 96.52 trades complete
- **THEN** `avg_price ≈ 85.30` after the two SELLs, and `realized_pnl = (85.30 - 96.52) * 195 ≈ -2188` after the BUY

## ADDED Requirements

### Requirement: Cancel stale entry orders before close
The strategy close path (squareoff or flip) SHALL call `OrderRouter.cancel_open_entry_orders(security_id, strategy_id)` before placing the covering BUY. This method SHALL transition all OPEN SELL orders for the given `(security_id, strategy_id)` pair to CANCELLED status and remove them from the paper engine's in-memory watch list.

#### Scenario: Stale SELL cancelled before covering BUY
- **WHEN** `cancel_open_entry_orders` is called for a security with one OPEN SELL order
- **THEN** that order's status is set to CANCELLED, `cancelled_at` is recorded, and the paper broker removes it from its watch list

#### Scenario: No stale orders — no-op
- **WHEN** `cancel_open_entry_orders` is called and no OPEN SELL orders exist for the security
- **THEN** the method returns without error and no DB writes occur
