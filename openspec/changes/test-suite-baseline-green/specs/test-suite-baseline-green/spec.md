## ADDED Requirements

### Requirement: The test suite SHALL pass in full and SHALL gate the build

`task test` SHALL exit non-zero when any test fails. A failing test SHALL NOT be documented as
accepted debt. Any test that cannot pass SHALL be marked `xfail` with `strict=True` and a reason
naming the change that will fix it, so that it fails the suite the moment it starts passing.

#### Scenario: A regression fails the build

- **WHEN** a change introduces a failing test
- **THEN** `task test` exits non-zero

#### Scenario: A quarantined test that starts passing fails the build

- **WHEN** a test marked `xfail(strict=True)` passes
- **THEN** the suite reports a failure, so the quarantine is removed rather than forgotten

#### Scenario: Quarantine carries an owner

- **WHEN** a test is marked `xfail`
- **THEN** its reason names the change identifier that will resolve it

### Requirement: The safety-critical loss-cap tests SHALL execute

The tests covering `KillSwitchService` and the hard day-loss cap SHALL construct their fixtures
successfully and SHALL assert the cap's behaviour. A safety mechanism SHALL NOT ship with a test file
that fails during fixture construction.

#### Scenario: The cap halts on a genuine breach

- **WHEN** realised day loss breaches the configured hard cap
- **THEN** the kill switch fires exactly once and the test asserts it

#### Scenario: The cap does not fire below the limit

- **WHEN** realised day loss is within the configured cap
- **THEN** the kill switch does not fire

#### Scenario: Fixtures construct

- **WHEN** the loss-cap test module is collected and run
- **THEN** no test errors during fixture construction

### Requirement: The suite SHALL assert the system's startup invariants

Tests SHALL assert that every runtime group marked required constructs and starts, so that an import
error or wiring fault in a live-trading subsystem fails the suite rather than degrading the running
system silently.

#### Scenario: A required group cannot be constructed

- **WHEN** a required runtime group raises during construction or start
- **THEN** a test fails

#### Scenario: A dead import is caught

- **WHEN** a module imports a name that does not exist in its source module
- **THEN** the suite fails rather than the application starting with a disabled subsystem

### Requirement: Event assertions SHALL distinguish the condition, not merely the event name

A test asserting that a critical event was emitted SHALL assert the condition that produced it, so
that an event type covering several conditions cannot satisfy an assertion about one of them.

#### Scenario: Cap and contradiction are distinguished

- **WHEN** a test asserts that a per-security lot cap was enforced
- **THEN** the assertion fails if the emitted event was produced by a leg-type contradiction instead

### Requirement: Static analysis of the application SHALL report no findings

`flutter analyze` SHALL report zero issues at every severity, and the analyzer SHALL be configured so
that an `info`-level finding fails the check.

#### Scenario: An info-level lint fails the check

- **WHEN** a change introduces an `info`-severity analyzer finding
- **THEN** `flutter analyze` exits non-zero
