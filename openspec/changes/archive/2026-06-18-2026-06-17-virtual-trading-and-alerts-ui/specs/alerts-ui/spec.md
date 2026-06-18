## ADDED Requirements

### Requirement: Alerts CRUD frontend

The system SHALL provide an `/alerts` route with a DataTable of all alerts (from `GET /api/v1/alerts`) showing columns: Symbol, Condition, Channels, Status (ARMED/TRIGGERED/RESOLVED Badge), and Actions (Edit, Delete). A "New Alert" button SHALL open a form dialog for creating alerts via `POST /api/v1/alerts`. Editing the threshold SHALL use `PATCH /api/v1/alerts/{id}` with `{threshold: <value>}`. Deletion SHALL use `DELETE /api/v1/alerts/{id}` with a confirmation dialog.

> **Note**: Toggle enabled/disabled is not yet supported — `AlertUpdate` schema (backend) has no `enabled` field. The alert lifecycle is `ARMED → TRIGGERED → RESOLVED` (auto-managed). A toggle action may be added in a future change once the backend model is extended.

#### Scenario: Create a price alert
- **WHEN** a user clicks "New Alert", selects NIFTY, sets condition "Price above 25000", and submits
- **THEN** `POST /api/v1/alerts` is called, the alert appears in the list with ARMED status

#### Scenario: Delete an alert with confirmation
- **WHEN** a user clicks Delete on an alert and confirms the dialog
- **THEN** `DELETE /api/v1/alerts/{id}` is called and the alert is removed from the list

---

### Requirement: Live alert notifications

The system SHALL connect to `/ws/alerts` via WebSocket and display a Toast notification whenever an alert is triggered. The Toast SHALL show the alert name, condition, and triggered value. Notifications SHALL appear regardless of the user's current page.

#### Scenario: Alert triggered notification
- **WHEN** a price alert "NIFTY breakout" triggers and the user is on the Trading page
- **THEN** a Toast notification appears: "Alert Triggered: NIFTY breakout — Price above 25000 (current: 25,012)"

---

### Requirement: OI/IV scanner view

The system SHALL provide a scanner view (tab or section on the Trading page) that fetches OI buildup and IV rank data from proposal #3's endpoints and displays a DataTable of actionable setups. Each row SHALL include: Strike, Type (CE/PE), OI Buildup classification (color-coded Badge), IV Rank, and a "Trade" action that opens the OrderEntry dialog pre-populated. If the analytics endpoints are unavailable (proposal #3 not yet implemented), the scanner SHALL display a graceful "Analytics upgrade required" message.

#### Scenario: Scanner shows OI buildup setups
- **WHEN** the scanner fetches OI buildup data showing 3 strikes with "long_buildup"
- **THEN** those 3 strikes appear in the scanner table with green "Long Buildup" badges

#### Scenario: Scanner degrades without analytics
- **WHEN** the OI buildup endpoint returns 404 (proposal #3 not implemented)
- **THEN** the scanner shows "Analytics upgrade required — install OI/IV Analytics proposal"
