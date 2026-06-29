## Purpose

This capability governs correctness requirements for P&L accounting in the paper engine, covering short-position weighted-average computation, orphan-position prevention, and monitor display fidelity.

## Requirements

## Requirement: Correct weighted average for short positions

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

## Requirement: No orphan positions from cancelled entry SELLs

The strategy close path (squareoff / flip) SHALL cancel any OPEN entry SELL orders for the current leg before placing the covering BUY. If no filled short position exists, no BUY SHALL be placed.

#### Scenario: Entry SELL cancelled before squareoff

- **WHEN** an entry SELL is placed but not yet filled, and a squareoff event fires for the same security
- **THEN** the OPEN SELL is cancelled before the BUY is sent, the BUY is NOT placed (nothing to close), and no net_qty change occurs on the position

#### Scenario: Entry SELL filled — squareoff proceeds normally

- **WHEN** an entry SELL has filled (status FILLED) and a squareoff event fires
- **THEN** a covering BUY for the full position qty is placed and the position is closed to net_qty = 0

## Requirement: Perl monitor blotter shows only filled orders

The Perl monitor SELL/BUY blotter SHALL include only orders with `status = FILLED`. CANCELLED and REJECTED orders SHALL be excluded from P&L rows and leg count.

#### Scenario: CANCELLED order absent from blotter

- **WHEN** the orders API returns a SELL order with `status = CANCELLED`
- **THEN** the Perl monitor does not render a row for that order and does not count it in the lot total or P&L

#### Scenario: FILLED order shown with correct P&L

- **WHEN** the orders API returns a SELL order with `status = FILLED` and a matching trade with `fill_price = 86.13`
- **THEN** the Perl monitor renders the row with `entry_px = 86.13` and a computed P&L

### Requirement: MARKET fills never record a zero average price
The paper engine SHALL fill a MARKET order at the best price available at placement time and SHALL
NOT persist a position whose `avg_price` is zero.

When a MARKET order is placed, the engine MUST use the cached last-traded price for the security
(e.g. Redis `ltp:<sid>`, populated by the tick router) rather than waiting for the next pub/sub
tick. If no price is yet known for the security, the order MUST remain pending (and retry on the
next tick) instead of filling at zero.

#### Scenario: Fill uses cached LTP immediately
- **WHEN** a MARKET order is placed for a security whose last-traded price is already cached
- **THEN** the order fills at that price (plus configured slippage)
- **AND** the resulting position `avg_price` is greater than zero

#### Scenario: No price yet — order does not fill at zero
- **WHEN** a MARKET order is placed for a security with no cached price
- **THEN** no position is persisted with `avg_price = 0`
- **AND** the order fills once a price becomes available

### Requirement: Realized P&L is never computed against a zero average
The paper engine SHALL NOT compute realized P&L for a position whose stored average price is zero
when that position is reduced or closed.

When `upsert_position` reduces or closes a position whose `old_avg` is zero, it MUST skip the
realized-P&L contribution (treating it as zero) and log a warning, so a fill-timing race can never
manufacture a `(0 − close_px)·qty` loss or profit.

#### Scenario: Closing a zero-average short yields zero realized
- **WHEN** a short position with `avg_price = 0` is closed by a covering BUY at 100
- **THEN** the realized P&L contribution from that close is 0 (not −100·qty)
- **AND** a warning is logged identifying the zero-average position

#### Scenario: Non-zero average closes normally
- **WHEN** a short position with `avg_price = 85.30` is closed by a BUY at 96.52
- **THEN** realized P&L is computed normally as `(85.30 − 96.52)·qty`
