# backtest

## ADDED Requirements

### Requirement: Leg-grouped trade summary
The backtest SHALL, in addition to any per-order detail, produce a leg-grouped summary in which
each open-through-cover leg is a single row. Scale-in orders SHALL be folded into their parent
leg via a running average entry price and a cumulative lot count. Each leg row SHALL report the
entry time (IST), the exit time (IST), the average entry price, the exit price, the lot count,
the realized leg profit and loss, and the close reason (one of flip, leg_stop, day_stop, or
square-off).

#### Scenario: Scale-ins fold into one leg
- **WHEN** a leg is opened and scaled in over several bars, then covered
- **THEN** the summary shows a single row whose average entry reflects all entry fills and whose
  lot count equals the total lots covered

#### Scenario: Close reason is reported
- **WHEN** a leg is closed by a flip, a per-leg stop, the daily loss cap, or end-of-day square-off
- **THEN** the leg row's reason column states which of those caused the close

#### Scenario: Leg P&L reconciles to the day total
- **WHEN** all leg rows for a day are summed
- **THEN** the total realized leg P&L equals the day's realized P&L reported by the per-order view
