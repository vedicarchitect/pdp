# backtest

## MODIFIED Requirements

### Requirement: Historical bar replay
The system SHALL replay historical market bars in chronological order, feeding them to the
strategy via the same event-driven interface as live trading. Source bars SHALL be fetched at
**1-minute** resolution and **resampled** to the strategy's signal timeframe in code, rather
than fetching a native bar of the signal timeframe directly, so the replayed series is
constructed by the same aggregation rule the live `BarAggregator` applies to the tick stream.
Resampling SHALL aggregate 1-minute bars on aligned UTC boundaries as open = first, high = max,
low = min, close = last, volume = sum.

#### Scenario: Bars arrive in correct order
- **WHEN** backtest processes historical bars for a security between two dates
- **THEN** bars are processed in ascending timestamp order, one at a time

#### Scenario: Signal timeframe is resampled from 1-minute bars
- **WHEN** the strategy's signal timeframe is 5m (or any multiple of one minute)
- **THEN** the backtest fetches 1-minute bars and aggregates them into the signal timeframe on
  aligned boundaries (open=first, high=max, low=min, close=last, volume=sum) before dispatch

#### Scenario: On-bar hook is invoked
- **WHEN** a resampled signal-timeframe bar is produced during replay
- **THEN** the strategy's `on_bar()` hook is called with that bar

#### Scenario: Missing bars in history
- **WHEN** backtest encounters a gap in 1-minute history
- **THEN** the system logs a warning with the gap period and continues processing
