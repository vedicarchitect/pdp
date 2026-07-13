## ADDED Requirements

### Requirement: A leg's type SHALL be persisted durably when the leg is opened

The strategy SHALL record each leg's type (`short`, `hedge` or `momentum`) together with its option
type, strike and expiry in PostgreSQL, in the same transaction that opens the leg. The type SHALL be
decided once, at open, and SHALL NOT be inferred at any later point from list membership, order side
or position sign.

#### Scenario: Opening a hedge records its type

- **WHEN** a protective hedge leg is opened
- **THEN** a durable row records `leg_kind = hedge` with its option type, strike and expiry, committed with the position

#### Scenario: Type is written exactly once

- **WHEN** a leg is opened, rolled and closed
- **THEN** its `leg_kind` is never rewritten to a different value

### Requirement: Leg rehydration SHALL read only the durable store

`_rehydrate_legs` SHALL classify restored legs from PostgreSQL alone. It SHALL NOT query the Mongo
`events` collection, which no code path writes. Every open `Position` for the strategy SHALL be
adopted into the in-memory leg structure.

#### Scenario: Round trip across a restart

- **WHEN** one short, one hedge and one momentum leg are open and the strategy is reconstructed against the same database
- **THEN** all three are restored with the correct type, option type, strike, lots and entry price

#### Scenario: No Mongo read occurs

- **WHEN** rehydration runs
- **THEN** the Mongo `events` collection is not queried

#### Scenario: A position with no durable leg row is adopted as an orphan

- **WHEN** an open `Position` exists for the strategy with no corresponding leg row
- **THEN** it is adopted, its type is inferred from the net-quantity sign, and one `LEG_TYPE_UNKNOWN` critical event names it

### Requirement: Rehydration SHALL be total or SHALL fail

Rehydration SHALL adopt every open position for the strategy or raise. It SHALL run to completion
before the strategy accepts its first tick. The precondition that the in-memory leg structure is
empty SHALL be asserted rather than used as an early return.

#### Scenario: Partial adoption is impossible

- **WHEN** rehydration fails to adopt one of several open positions
- **THEN** it raises and the strategy does not begin processing ticks

#### Scenario: Rehydration precedes the first tick

- **WHEN** the strategy host starts a strategy with open positions
- **THEN** no tick is delivered until rehydration has completed

#### Scenario: Empty precondition is asserted

- **WHEN** rehydration is invoked with a non-empty leg structure
- **THEN** it raises, rather than returning silently as a no-op

### Requirement: A contradiction between the durable leg type and the broker position SHALL halt trading for that underlying

The platform SHALL emit a `LEG_TYPE_CONTRADICTED` critical event when a leg's persisted type implies
a position sign that contradicts the broker's actual net quantity. It SHALL close the position using
the side implied by the broker's sign, and in live mode SHALL halt new entries for that underlying
for the remainder of the session.

#### Scenario: Sign contradicts the persisted type

- **WHEN** a leg persisted as `short` is found with a positive broker net quantity
- **THEN** a `LEG_TYPE_CONTRADICTED` critical event is emitted and the close order uses `SELL`

#### Scenario: Live mode halts the underlying

- **WHEN** a contradiction is detected while `LIVE` is true
- **THEN** no new leg is opened for that underlying for the rest of the session

#### Scenario: Paper mode records but continues

- **WHEN** a contradiction is detected in paper mode
- **THEN** the event is emitted and the session continues, so the defect can be studied

#### Scenario: The position is never grown

- **WHEN** any close executes against a position whose sign contradicts the leg's persisted type
- **THEN** the resulting absolute net quantity is strictly less than before the order
