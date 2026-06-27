## ADDED Requirements

### Requirement: Retired — React shell removed
This capability (Vite/React app shell, TanStack router, React sidebar) SHALL be considered retired with `frontend/`. All active shell and navigation requirements MUST be sourced from `trading-app` "Responsive app shell and navigation" instead.

#### Scenario: No active requirements
- **WHEN** this spec is referenced
- **THEN** redirect to `trading-app` "Responsive app shell and navigation" for the active shell requirement

## REMOVED Requirements

### Requirement: Vite + React scaffold initialised
**Reason**: Removed with `frontend/`; replaced by the Flutter scaffold in `trading-app`.
**Migration**: See `trading-app` "Flutter application scaffold".

### Requirement: Six route stubs registered
**Reason**: React TanStack routes removed with `frontend/`.
**Migration**: Flutter uses `go_router`; this slice ships the shell + live portfolio, other routes follow as later changes.

### Requirement: Navigation sidebar present
**Reason**: React sidebar removed with `frontend/`.
**Migration**: See `trading-app` "Responsive app shell and navigation" (NavigationBar/Rail).

### Requirement: TanStack Query provider configured
**Reason**: React data layer removed with `frontend/`.
**Migration**: Flutter uses Riverpod providers; see `trading-app`.

### Requirement: WebSocket hooks implemented
**Reason**: React hooks removed with `frontend/`.
**Migration**: See `trading-app` "Realtime WebSocket client with backoff reconnect".

### Requirement: lightweight-charts charting placeholder
**Reason**: React charting component removed with `frontend/`.
**Migration**: Flutter uses `fl_chart`; see `trading-app` "Live portfolio screen".

### Requirement: PAPER / LIVE mode banner
**Reason**: React banner removed with `frontend/`.
**Migration**: Flutter derives mode from `portfolio summary.mode`; see `trading-app`.

### Requirement: Vite dev proxy configured
**Reason**: Vite-specific dev proxy removed with `frontend/`.
**Migration**: Flutter uses `--dart-define` backend config; see `trading-app` "Configurable backend connection".

### Requirement: shadcn/ui + utility infrastructure
**Reason**: shadcn/React tooling removed with `frontend/`.
**Migration**: None — Flutter Material + shared widgets replace it.

### Requirement: Collapsible command-center sidebar
**Reason**: React sidebar behavior removed with `frontend/`.
**Migration**: Flutter NavigationRail (wide) / NavigationBar (compact); see `trading-app`.

### Requirement: Grouped navigation sections
**Reason**: React sidebar grouping removed with `frontend/`.
**Migration**: Navigation destinations defined in the Flutter shell; grouping revisited as routes grow.

### Requirement: Mobile responsive sidebar
**Reason**: React responsive sidebar removed with `frontend/`.
**Migration**: See `trading-app` responsive shell (bottom bar on compact widths).
