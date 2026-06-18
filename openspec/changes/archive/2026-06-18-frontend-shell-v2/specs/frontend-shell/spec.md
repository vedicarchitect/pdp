## MODIFIED Requirements

### Requirement: Collapsible command-center sidebar

The sidebar SHALL support two states: expanded (showing icons + labels + section headers) and collapsed (icons only with tooltips). The current state SHALL be persisted in `localStorage`. A toggle button in the sidebar header SHALL switch between states.

#### Scenario: Sidebar toggles between expanded and collapsed
- **WHEN** the user clicks the collapse toggle
- **THEN** the sidebar transitions to icon-only mode, and nav item labels appear as tooltips on hover

#### Scenario: Sidebar state persists across page loads
- **WHEN** the user collapses the sidebar and refreshes the page
- **THEN** the sidebar loads in collapsed state

---

### Requirement: Grouped navigation sections

The sidebar SHALL organize nav items into labeled groups: TRADING (Dashboard, Intraday, Positional, Strategies), OPTIONS (Analytics, Builder), DATA (Portfolio, Instruments, Backtest), and SYSTEM (Events, Alerts, Operations). Section headers SHALL be visible in expanded mode and hidden in collapsed mode.

#### Scenario: Nav items are grouped under section headers
- **WHEN** the sidebar is expanded
- **THEN** section headers (TRADING, OPTIONS, DATA, SYSTEM) are visible with their child nav items beneath

---

### Requirement: Mobile responsive sidebar

On viewports below `768px`, the sidebar SHALL be hidden by default and accessible via a hamburger menu button. Tapping the hamburger opens the sidebar as a full-height overlay. Tapping outside or pressing Escape closes it.

#### Scenario: Mobile sidebar opens as overlay
- **WHEN** the viewport is 375px wide and the user taps the hamburger icon
- **THEN** the sidebar appears as a full-height overlay on the left

#### Scenario: Mobile sidebar closes on outside tap
- **WHEN** the mobile sidebar overlay is open and the user taps outside it
- **THEN** the overlay closes
