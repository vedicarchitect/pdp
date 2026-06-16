## MODIFIED Requirements

### Requirement: Order execution simulation
The system SHALL accept orders from the strategy during backtest and execute them at bar close (OHLC)
with no slippage, immediately confirming fills. Fills SHALL be **non-anticipatory**: when an action is
triggered by the signal computed from bar N (which uses bar N's close), the system SHALL fill that
action at a price no earlier than bar N's close — it SHALL NOT fill at bar N's open or any earlier
bar. This prohibition applies uniformly to position entries, scale-ins, flip-driven exits and
re-entries, stop-driven exits, and square-offs, so that no leg is ever priced off a bar that precedes
the bar whose close produced the decision.

#### Scenario: Market order fills at bar close
- **WHEN** strategy places a market order during on_bar() hook
- **THEN** system fills the order at the bar's close price at end of bar processing

#### Scenario: Flip exit is not priced before the triggering bar
- **WHEN** a SuperTrend flip is detected from bar N's close and the open position is closed on that flip
- **THEN** the exit is filled at bar N's close (or a later bar's open), never at bar N's open

#### Scenario: Flip re-entry is not priced before the triggering bar
- **WHEN** a flip on bar N's close opens a new opposite-side leg
- **THEN** the new entry is filled at bar N's close (or a later bar's open), never at bar N's open

#### Scenario: Exit fill does not reach a future bar
- **WHEN** the bar matching the fill timestamp is missing and a nearest-bar tolerance is applied
- **THEN** the tolerance SHALL NOT select a bar later than the decision bar for an exit, so no
  look-ahead price is used

#### Scenario: Position limit enforcement
- **WHEN** strategy tries to exceed configured position limits
- **THEN** system rejects the order and logs rejection reason

#### Scenario: Order is rejected
- **WHEN** strategy places an order that violates constraints
- **THEN** order is not executed and a rejection event is sent to strategy
