## ADDED Requirements

### Requirement: Open-leg recovery on restart
When a strategy process restarts during the same trading day, the strategy SHALL query the positions
table on startup and, if a non-zero short position tagged to this strategy exists for any of its
instruments, reconstruct the in-memory open-leg state (security_id, segment, option_type, strike,
and lot count) from that position so no ghost-position accumulation occurs on the next flip.

#### Scenario: Strategy restarts with open short leg
- **WHEN** a strategy process restarts and the positions table contains a non-zero short position (net_qty < 0) tagged to this strategy for a current trading-day fill
- **THEN** the strategy initializes `_current` from that position (lots = abs(net_qty) // lot_size, option_type and strike from the instruments table) and logs a `state_recovered` event

#### Scenario: Strategy restarts flat
- **WHEN** a strategy process restarts and no non-zero position exists for this strategy
- **THEN** the strategy initializes `_current = None` (unchanged from normal startup) and no recovery event is logged

#### Scenario: Cross-day restart is ignored
- **WHEN** a strategy process restarts and the only non-zero position belongs to a prior calendar day (IST)
- **THEN** the strategy treats the position as stale, initializes flat, and logs a warning

### Requirement: Day P&L baseline recovery on restart
When a strategy process restarts during the same trading day, the strategy SHALL read the current
per-security realized P&L from the ledger at startup and store it as the day baseline, so the
running day_pnl correctly reflects losses realized before the restart.

#### Scenario: Day P&L continues from before crash
- **WHEN** a strategy process restarts after realizing losses pre-crash
- **THEN** `_day_realized()` returns the correct cumulative day loss from the moment the trading day started, not zero

#### Scenario: No prior fills — baseline is zero
- **WHEN** a strategy process restarts before any fills have occurred
- **THEN** the baseline is zero and day_pnl behaves identically to a normal first start
