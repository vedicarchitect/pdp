# feed-health Specification

## Purpose
Requirements for detecting and recovering from degraded market-data feed conditions: stale-feed watchdog, configurable reconnect timing.

## Requirements

### Requirement: Stale-feed watchdog
The system SHALL detect a connected-but-silent tick feed during market hours and force a reconnect,
emitting a `feed_stale` event, without auto-evicting subscriptions.

#### Scenario: Silent feed during market hours triggers reconnect
- **WHEN** no tick has been received for longer than `FEED_STALE_SECONDS` while inside the trading
  session and the socket reports connected
- **THEN** a `feed_stale` structlog event is emitted
- **AND** the existing reconnect routine is triggered

#### Scenario: Quiet feed outside market hours is not flagged
- **WHEN** no ticks arrive outside the trading session
- **THEN** no `feed_stale` event is emitted and no reconnect is forced

#### Scenario: Reconnect preserves subscriptions
- **WHEN** the watchdog forces a reconnect
- **THEN** existing subscriptions are restored after reconnect (no manual resubscribe required)

---

### Requirement: Configurable reconnection timing
The system SHALL read the reconnect base and maximum backoff delays from settings rather than
hardcoded constants.

#### Scenario: Reconnect delays come from settings
- **WHEN** the adapter computes a reconnect backoff
- **THEN** the base and ceiling are taken from `FEED_RECONNECT_BASE_DELAY` and
  `FEED_RECONNECT_MAX_DELAY` via `get_settings()`
