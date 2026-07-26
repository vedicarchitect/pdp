## ADDED Requirements

### Requirement: An entry order's real-world outcome SHALL NOT be silently discarded

The strategy SHALL confirm that an entry order's cancel actually took effect before treating an
aborted entry as a no-op. When `_open_short` cannot resolve a fill price within its bounded wait
and the underlying order could not be cancelled — because it already filled, or a fill is already
in flight — the strategy SHALL register the resulting position as a tracked leg (using the real
fill price) instead of returning as if nothing was opened.

This prevents an order that fills moments after the strategy gives up on it (e.g. during a tick
backpressure/drop event) from landing as a broker position with no corresponding in-memory leg —
a position the strategy cannot manage, stop, or square off.

#### Scenario: Cancel succeeds — abort is clean

- **WHEN** `_open_short` cannot resolve a fill price and cancels the entry order
- **AND** the cancel confirms the order was removed before ever filling
- **THEN** no leg is registered and no broker position results, matching the "nothing opened"
  return contract

#### Scenario: Cancel races a real fill — the leg is not orphaned

- **WHEN** `_open_short` cannot resolve a fill price within its wait budget and calls
  `cancel_open_entry_orders`
- **AND** the order had already filled (or fills concurrently with the cancel attempt)
- **THEN** the strategy registers the filled leg using the real fill price rather than discarding
  it, and the resulting broker position has a matching in-memory `_legs` entry
