## ADDED Requirements

### Requirement: Retired — React alerts UI removed
This capability (React alerts UI) SHALL be considered retired with `frontend/`. Future alerts UI requirements MUST be specified in a new Flutter alerts change reusing the `trading-app` data/provider pattern. The backend `alerts` capability and `/api/v1/alerts` are unaffected.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to a future Flutter alerts change for active requirements

## REMOVED Requirements

### Requirement: Alerts CRUD frontend
**Reason**: React alerts UI removed with `frontend/`. Backend `alerts` capability and `/api/v1/alerts` are unaffected.
**Migration**: A Flutter alerts screen is a later change reusing the `trading-app` data/provider pattern.

### Requirement: Live alert notifications
**Reason**: React `/ws/alerts` consumer removed with `frontend/`.
**Migration**: Reintroduced via the Flutter WS-client when the alerts screen lands.

### Requirement: OI/IV scanner view
**Reason**: React scanner removed with `frontend/`.
**Migration**: Reintroduced in a future Flutter analytics/scanner change.
