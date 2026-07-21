## MODIFIED Requirements

### Requirement: Flutter Live Events sidebar consumes the backend event stream

The app SHALL present a Live Events sidebar that seeds from `GET /api/v1/events` and then
streams live events from `WS /ws/events`, rendering the meaningful market-structure events
the backend publishes (EMA crossover, price/EMA break, SuperTrend flip, Camarilla touch,
level break) for NIFTY/BANKNIFTY/SENSEX across all configured timeframes. The event parser
SHALL match the backend `Event.to_dict()` contract: it SHALL accept WS frames that carry an
`event_type` (there is no `type` envelope field), read the timestamp from `ts` (falling back
to `timestamp`), and normalise `severity` case-insensitively so backend `INFO`/`WARNING`/
`ERROR`/`CRITICAL` values map to the correct visual styling. Live frames SHALL append to the
feed, not only the initial REST backfill.

The REST backfill SHALL read the event list from the backend `Page` envelope's `items` key
(the `GET /api/v1/events` response is a `Page`, not a bare list, and not an `events`-keyed
object). The parser SHALL read `underlying`/`timeframe`/`title` from the top-level frame when
present (the WS shape) and otherwise from the nested `data` map (the REST `EventOut` shape), so
both sources populate those labels.

#### Scenario: Live WS event appended

- **WHEN** the backend publishes a `SUPERTREND_FLIP` event to `/ws/events` while the sidebar is open
- **THEN** the event is parsed (via its `event_type` and `ts`) and appended to the Live Events feed without requiring a refresh

#### Scenario: Severity styling from backend case

- **WHEN** an event arrives with `severity: "CRITICAL"` or `"WARNING"`
- **THEN** it renders with the loss/warning styling respectively, not the default info styling

#### Scenario: Backend REST backfill parses from the Page envelope

- **WHEN** the sidebar seeds from `GET /api/v1/events` and the response is a `Page` with events under `items`
- **THEN** each event under `items` parses successfully and is shown, and its `underlying`/`timeframe`/`title` are read from the event's nested `data` map when not present top-level

#### Scenario: Empty vs populated feed is driven by content, not an envelope-key mismatch

- **WHEN** the backend returns one or more events under `items`
- **THEN** the sidebar renders them rather than showing the empty "No events to show" state

### Requirement: Execution tab shows meaningful events, not strategy heartbeats

The Execution tab SHALL surface the Live Events sidebar (market-structure events) and SHALL
NOT render the strategy heartbeat log (`bias_evaluated`, `leg_status`, repeated `leg_open`)
as its event feed. The monitor payload MAY still carry `recent_events` for debugging, but the
Execution tab UI SHALL NOT present that heartbeat list as the primary event view.

#### Scenario: No heartbeat list on the Execution tab

- **WHEN** the user opens the Execution tab while the strangle is running
- **THEN** the meaningful Live Events sidebar is visible and the `bias_evaluated`/`leg_status` heartbeat list is not shown
