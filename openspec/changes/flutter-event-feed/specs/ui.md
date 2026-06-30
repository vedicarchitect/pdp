# Event Feed UI Spec

## Layout Rules
- **Wide Screens (>= 720px):** `EventFeedSidebar` is mounted in a `Row` directly inside `AppShell` with a fixed width of `300px`.
- **Compact Screens (< 720px):** `AppShell` renders a "Notifications" icon in the `AppBar` actions list, which opens an `EndDrawer` containing the `EventFeedSidebar`.

## The Sidebar
- **Header:** Features a "Live Events" title and a settings icon to open the configuration dialog.
- **List:** Displays up to 100 events, scrolled vertically.
- **Event Item (`_EventTile`):**
  - **Alerts (Red):** `Icons.warning_rounded`
  - **Warnings (Amber):** `Icons.info_outline`
  - **Info (Green):** `Icons.bolt`
  - Displays the timestamp (`HH:mm`), Security ID, event message, and an event type pill (colored depending on severity).

## Config Dialog (`EventConfigDialog`)
- Shows a list of `SwitchListTile` elements for each event type (e.g., `crossover`, `breakout`).
- Toggling the switch updates the `EventsSource` via `patchConfig`.
- Configured dynamically from `EventConfig.eventTypePush`.
