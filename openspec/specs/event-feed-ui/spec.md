# event-feed-ui Specification

## Purpose
TBD - created by archiving change 2026-06-17-event-feeder. Update Purpose after archive.
## Requirements
### Requirement: Live event feed page

The system SHALL provide an `/events` route displaying a reverse-chronological feed of platform events. Events SHALL be fetched from `GET /api/v1/events` for history and streamed live via `/ws/events` WebSocket. Each event SHALL render as a card with: timestamp (relative, e.g., "2m ago"), event type icon, severity badge (info/warning/error/critical), title, description, and optional action link.

#### Scenario: Event feed loads history
- **WHEN** a user navigates to `/events` with 50 historical events
- **THEN** the feed displays events in reverse chronological order with the newest first

#### Scenario: Real-time event appears in feed
- **WHEN** an order fill event is emitted while the user is viewing `/events`
- **THEN** the event appears at the top of the feed within 1 second without manual refresh

#### Scenario: Filter by event type
- **WHEN** a user selects only "Strategy Signal" and "Order Fill" event type filters
- **THEN** only events of those types are displayed in the feed

#### Scenario: Filter by severity
- **WHEN** a user selects "Warning" severity filter
- **THEN** only warning-level events are displayed

---

### Requirement: Event type and severity visual mapping

Each event type SHALL have a dedicated icon from the lucide-react library (e.g., `AlertOctagon` for kill-switch, `CheckCircle` for order fills, `Zap` for strategy signals). Each severity level SHALL map to a Badge variant: info (blue), warning (amber), error (red), critical (red with pulse animation).

#### Scenario: Kill-switch event renders with correct visuals
- **WHEN** a kill-switch-triggered event is displayed
- **THEN** it shows an `AlertOctagon` icon with a red pulsing "Critical" badge

---

### Requirement: Web Push notification opt-in

The events page SHALL provide a "Enable Push Notifications" button that initiates the Web Push subscription flow: fetch VAPID key from `GET /api/v1/events/vapid-key`, request browser notification permission, register a service worker, subscribe via `pushManager.subscribe()`, and send the subscription to `POST /api/v1/events/push/subscribe`. The current opt-in status SHALL be displayed.

#### Scenario: Successful push opt-in
- **WHEN** a user clicks "Enable Push Notifications" and grants browser permission
- **THEN** the subscription is sent to the server and the UI shows "Push enabled ✓"

#### Scenario: Browser permission denied
- **WHEN** a user clicks "Enable Push Notifications" and denies browser permission
- **THEN** the UI shows an explanation message: "Notifications blocked by browser. Enable in browser settings."

---

### Requirement: Per-event notification configuration

The events page SHALL display a configuration panel (from `GET /api/v1/events/config`) with toggle switches for each event type's push notification setting. Toggling a switch SHALL update the notification preference for that event type.

#### Scenario: Disable push for strategy signals
- **WHEN** a user toggles off "Strategy Signal" push notifications
- **THEN** strategy signal events no longer trigger browser push notifications (but still appear in the feed)

---

### Requirement: Sidebar unread event badge

The sidebar Events link SHALL display a numeric badge showing the count of events received since the user's last visit to `/events`. The count SHALL be tracked via a `localStorage` timestamp. The badge SHALL disappear when the user navigates to `/events`.

#### Scenario: Unread badge shows count
- **WHEN** 5 events arrive while the user is on the Trading page
- **THEN** the Events sidebar link shows a badge with "5"

#### Scenario: Badge clears on visit
- **WHEN** the user navigates to `/events`
- **THEN** the unread badge disappears from the sidebar

