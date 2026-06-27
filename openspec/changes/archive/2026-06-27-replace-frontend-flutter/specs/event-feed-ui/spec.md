## ADDED Requirements

### Requirement: Retired — React event feed UI removed
This capability (React events page, Web Push) SHALL be considered retired with `frontend/`. Future event feed UI requirements MUST be specified in a new Flutter events change reusing the `trading-app` shell + WS-client pattern. The backend `events` capability and `/ws/events` are unaffected.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to a future Flutter events change for active requirements

## REMOVED Requirements

### Requirement: Live event feed page
**Reason**: React events page removed with `frontend/`. The backend `events` capability and `/ws/events` are unaffected.
**Migration**: A Flutter events screen is a later change reusing the `trading-app` shell + WS-client pattern.

### Requirement: Event type and severity visual mapping
**Reason**: React-only mapping removed with `frontend/`.
**Migration**: Reintroduced in the future Flutter events screen.

### Requirement: Web Push notification opt-in
**Reason**: Browser Web Push is React/PWA-specific and removed with `frontend/`.
**Migration**: Native push (FCM/local notifications) is a separate future change; backend push endpoints remain.

### Requirement: Per-event notification configuration
**Reason**: React config UI removed with `frontend/`. Backend `/api/v1/events/config` is unaffected.
**Migration**: Reintroduced in the future Flutter events screen.

### Requirement: Sidebar unread event badge
**Reason**: React sidebar badge removed with `frontend/`.
**Migration**: Reintroduced on the Flutter shell when the events screen lands.
