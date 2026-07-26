## ADDED Requirements

### Requirement: A flat position SHALL NOT carry stale unrealized P&L

Whenever a paper `Position`'s `net_qty` transitions to zero, the paper engine SHALL reset
`unrealized_pnl` to zero in the same update. A flat position SHALL NOT display a nonzero
mark-to-market carried over from before it was closed.

#### Scenario: Closing a position zeroes its unrealized P&L

- **WHEN** a fill or a sequence of fills brings a position's `net_qty` to 0
- **THEN** the position's `unrealized_pnl` is 0 in the same update, regardless of what it was
  immediately before the close

#### Scenario: A still-open position keeps its live unrealized P&L

- **WHEN** a position's `net_qty` remains nonzero after a partial fill
- **THEN** `unrealized_pnl` continues to reflect live mark-to-market and is not reset

#### Scenario: A stale cached mark-to-market cannot overwrite a just-flattened position

- **WHEN** the portfolio MTM service's periodic flush writes its in-memory `unrealized_pnl` for a
  position whose cache entry has not yet reloaded from the database since a fill flattened it
- **THEN** the flush does not modify that position's row — a write is only applied to positions
  the database still shows as `net_qty != 0`
