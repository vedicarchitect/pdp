## ADDED Requirements

### Requirement: The execution monitor SHALL render at every viewport width

The execution monitor tab SHALL lay out without exception at any window width, on desktop and mobile.
A scrollable nested inside another scrollable SHALL shrink-wrap and SHALL NOT scroll independently,
so that the outer scrollable is the sole scroll surface and no viewport receives an unbounded main-axis
constraint.

#### Scenario: Narrow viewport with open positions

- **WHEN** the tab renders at 500 logical pixels wide with open legs
- **THEN** no exception is thrown and the positions and indicator panel are both reachable by scrolling

#### Scenario: Narrow viewport with no positions

- **WHEN** the tab renders at 500 logical pixels wide with an empty position list
- **THEN** no exception is thrown and the empty-state message is shown

#### Scenario: Window narrower than the split breakpoint

- **WHEN** the tab renders at 821 logical pixels wide on desktop
- **THEN** it takes the stacked layout and no exception is thrown

#### Scenario: Wide viewport

- **WHEN** the tab renders at 1400 logical pixels wide
- **THEN** the indicator panel is docked beside the positions column and no exception is thrown

### Requirement: The index price strip SHALL NOT overflow or truncate an index name

The index price strip SHALL fit its contents at any viewport width, scaling its text down rather than
overflowing its bounds or eliding the index name.

#### Scenario: Phone-width strip

- **WHEN** the strip renders three indices at 500 logical pixels wide
- **THEN** no overflow is reported and each index name is fully legible

#### Scenario: Long index name and price

- **WHEN** an index name and price together exceed the cell's share of the strip
- **THEN** the content is scaled down and the index name is not replaced by an ellipsis

### Requirement: A widget that branches on a width breakpoint SHALL be tested on both sides of it

Any presentation widget selecting its layout from a width breakpoint SHALL have widget tests that
pump it at a viewport below and above that breakpoint, each asserting no exception was thrown.

#### Scenario: Both branches are covered

- **WHEN** a widget's layout depends on a width breakpoint
- **THEN** the test suite pumps it at a width on each side of the breakpoint and asserts no exception

#### Scenario: A regression in the untested branch fails the suite

- **WHEN** a change breaks layout only below the breakpoint
- **THEN** the narrow-viewport test fails
