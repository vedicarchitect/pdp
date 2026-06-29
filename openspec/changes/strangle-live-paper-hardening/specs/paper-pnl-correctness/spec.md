## ADDED Requirements

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
