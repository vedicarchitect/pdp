# supertrend-strategy

A paper-only intraday strategy that sells options in the direction of a SuperTrend(3,1)
signal on the NIFTY index, scales in while the trend holds, and squares off by end of day.

## ADDED Requirements

### Requirement: Signal-aligned option selling
The strategy SHALL, on each closed signal-timeframe bar, sell an out-of-the-money option of
the nearest weekly expiry aligned with the current SuperTrend direction: short PE when the
trend is up (green), short CE when the trend is down (red).

#### Scenario: Open short PE on uptrend
- **WHEN** there is no open leg and SuperTrend direction is up
- **THEN** the strategy sells the configured OTM PE at the starting lot size

#### Scenario: Open short CE on downtrend
- **WHEN** there is no open leg and SuperTrend direction is down
- **THEN** the strategy sells the configured OTM CE at the starting lot size

### Requirement: Flip closes and reverses
The strategy SHALL, when the SuperTrend direction flips against the open leg, buy back the
open leg and open the opposite-side leg at the starting lot size.

#### Scenario: Up-to-down flip
- **WHEN** a short PE leg is open and SuperTrend flips to down
- **THEN** the strategy buys back the PE and sells the OTM CE at the starting lot size

### Requirement: Scale-in while trend holds
The strategy SHALL add a configured number of lots on each subsequent signal bar while the
SuperTrend direction is unchanged, up to a configured maximum lot count.

#### Scenario: Add a lot on continued trend
- **WHEN** a leg is open, the direction is unchanged on a new bar, and open lots < max
- **THEN** the strategy sells `add_lots` more of the same option

#### Scenario: Respect the max-lots cap
- **WHEN** open lots already equal the maximum
- **THEN** the strategy does not add more lots

### Requirement: Trading window and square-off
The strategy SHALL place no new entries before the configured start time (IST) and SHALL flat
all legs at the configured square-off time (IST), trading no more that day.

#### Scenario: No entries before start
- **WHEN** the current IST time is before the start time
- **THEN** the strategy places no orders

#### Scenario: Square-off at end of window
- **WHEN** the current IST time is at or past the square-off time and a leg is open
- **THEN** the strategy buys back the open leg and stops trading for the day

### Requirement: Paper-only routing
The strategy SHALL route all orders through the platform order router, which is paper unless
live trading is explicitly enabled and a broker is configured.

#### Scenario: Orders route to paper by default
- **WHEN** the strategy places an order and live mode is not enabled
- **THEN** the order is filled by the paper engine
