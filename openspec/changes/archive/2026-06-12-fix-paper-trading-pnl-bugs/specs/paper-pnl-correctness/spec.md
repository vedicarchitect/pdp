## ADDED Requirements

### Requirement: Correct weighted average for short positions
The paper engine SHALL compute `avg_price` for a short position using the absolute value of `old_qty` when adding to an existing short. Specifically: `total_cost = old_avg * abs(old_qty) + fill_price * order_qty`, divided by `abs(new_qty)`.

#### Scenario: Single-leg short — avg equals fill price
- **WHEN** a SELL order for 130 units at 86.13 fills and no prior position exists
- **THEN** the position has `net_qty = -130` and `avg_price = 86.13`

#### Scenario: Multi-leg short — avg is weighted correctly
- **WHEN** SELL 130 @ 86.13 fills, then SELL 65 @ 83.63 fills for the same security
- **THEN** the position has `net_qty = -195` and `avg_price = (86.13*130 + 83.63*65) / 195 ≈ 85.30`

#### Scenario: Multi-leg short close — realized P&L is correct
- **WHEN** a 5-leg short with average entry ≈ 85.30 is closed by a single BUY 325 @ 96.52
- **THEN** `realized_pnl = (85.30 - 96.52) * 325 ≈ -3645` (negative — a loss) and `net_qty = 0`

### Requirement: No orphan positions from cancelled entry SELLs
The strategy close path (squareoff / flip) SHALL cancel any OPEN entry SELL orders for the current leg before placing the covering BUY. If no filled short position exists, no BUY SHALL be placed.

#### Scenario: Entry SELL cancelled before squareoff
- **WHEN** an entry SELL is placed but not yet filled, and a squareoff event fires for the same security
- **THEN** the OPEN SELL is cancelled before the BUY is sent, the BUY is NOT placed (nothing to close), and no net_qty change occurs on the position

#### Scenario: Entry SELL filled — squareoff proceeds normally
- **WHEN** an entry SELL has filled (status FILLED) and a squareoff event fires
- **THEN** a covering BUY for the full position qty is placed and the position is closed to net_qty = 0

### Requirement: Perl monitor blotter shows only filled orders
The Perl monitor SELL/BUY blotter SHALL include only orders with `status = FILLED`. CANCELLED and REJECTED orders SHALL be excluded from P&L rows and leg count.

#### Scenario: CANCELLED order absent from blotter
- **WHEN** the orders API returns a SELL order with `status = CANCELLED`
- **THEN** the Perl monitor does not render a row for that order and does not count it in the lot total or P&L

#### Scenario: FILLED order shown with correct P&L
- **WHEN** the orders API returns a SELL order with `status = FILLED` and a matching trade with `fill_price = 86.13`
- **THEN** the Perl monitor renders the row with `entry_px = 86.13` and a computed P&L
