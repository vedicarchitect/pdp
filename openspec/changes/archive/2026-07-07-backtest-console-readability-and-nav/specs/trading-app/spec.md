## MODIFIED Requirements

### Requirement: Responsive app shell and navigation
The system SHALL provide an app shell that adapts to viewport width: a bottom
`NavigationBar` on compact widths (phones) and a side `NavigationRail` on wide widths
(desktop/tablet), driven by a single breakpoint. The shell SHALL host the routed screens via
`go_router` and SHALL display a connection-status indicator and the PAPER/LIVE mode badge. Each
primary screen SHALL have exactly one entry point in the navigation: the Execution and Journal
screens live in the left nav (their primary home) and SHALL NOT be duplicated as tabs inside the
Management Hub. The Management Hub SHALL host only Strategies, Housekeeping, and Jobs/Audit.

#### Scenario: Compact layout uses a bottom bar
- **WHEN** the window is narrower than the breakpoint
- **THEN** navigation is presented as a bottom `NavigationBar`

#### Scenario: Wide layout uses a rail
- **WHEN** the window is wider than the breakpoint
- **THEN** navigation is presented as a side `NavigationRail`

#### Scenario: No duplicate Execution/Journal entry points

- **WHEN** the user opens the Management Hub
- **THEN** it shows only Strategies, Housekeeping, and Jobs/Audit — Execution and Journal appear
  only in the left nav, each with a single entry point
