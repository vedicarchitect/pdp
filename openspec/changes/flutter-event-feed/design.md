# Flutter Event Feed - Design

## Architecture
The event feed operates as an independent feature slice within the `events` directory. It adheres to the standard Domain, Data, Application, and Presentation layers:
1. **Domain**: `AppEvent` and `EventConfig` define the data structures. The `EventsSource` interface defines the contract.
2. **Data**: 
   - `MockEventsSource`: Generates mock anomalies/crossovers every 15s to facilitate UI testing.
   - `LiveEventsSource`: Connects to `GET /api/v1/events` for the initial load and listens to `WS /ws/events` for real-time appends. Modifies config state via `PATCH /api/v1/events/config`.
3. **Application**: Riverpod provides instances of `EventsSource` (Live/Mock) and a `StreamProvider` for realtime UI updates.
4. **Presentation**: `EventFeedSidebar` renders the list of events (colored by severity). Depending on the layout (managed by `AppShell`), the sidebar is persistently attached to the right of the screen (on wide screens) or accessed via an `EndDrawer` (on mobile).

## Configuration Strategy
The frontend reads push preferences from `/api/v1/events/config` and renders toggles for each available `eventType`. When a toggle is modified, it issues a `PATCH` request to sync state with the backend event publisher.
