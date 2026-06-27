## ADDED Requirements

### Requirement: Retired — React order entry UI removed
This capability (React order-entry dialog, trading page) SHALL be considered retired with `frontend/`. Future order-entry UI requirements MUST be specified in a new Flutter order-entry change. The backend `order-execution` capability and `/api/v1/orders` are unaffected.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to a future Flutter order-entry change for active requirements

## REMOVED Requirements

### Requirement: Order entry UI component
**Reason**: React order-entry dialog removed with `frontend/`. Backend `order-execution` and `/api/v1/orders` are unaffected.
**Migration**: A Flutter order-entry screen is a later change reusing the `trading-app` shell + data pattern.

### Requirement: Trading page with orders, trades, and positions
**Reason**: React trading page removed with `frontend/`.
**Migration**: Reintroduced as a Flutter trading screen in a later change.

### Requirement: Instrument search picker
**Reason**: React instrument picker removed with `frontend/`. Backend `/api/v1/instruments` is unaffected.
**Migration**: Reintroduced in the future Flutter order-entry / instruments screen.
