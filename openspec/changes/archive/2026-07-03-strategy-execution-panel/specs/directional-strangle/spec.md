## ADDED Requirements

### Requirement: Leg entry metadata

Each open leg SHALL record `entry_time` (IST timezone-aware) and `entry_reason` (a short string
capturing the bias bucket and score at entry, e.g. `NEUTRAL@0.10`) when the leg is opened, for short,
hedge, and momentum legs. The `state()` API SHALL include `entry_time` and `entry_reason` in each leg's
dict so the monitor can display when and why each leg was opened. Closed-leg exit reasons remain sourced
from the existing `_activity` event buffer.

#### Scenario: Entry metadata captured on open

- **WHEN** a short leg is opened in the NEUTRAL bucket with score 0.10
- **THEN** the leg's `entry_time` is set to the IST open time and `entry_reason` is `"NEUTRAL@0.10"`

#### Scenario: Entry metadata exposed in state

- **WHEN** `state()` is called with at least one open leg
- **THEN** each leg dict includes `entry_time` and `entry_reason`
