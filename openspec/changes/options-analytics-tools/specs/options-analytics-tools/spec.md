## ADDED Requirements

### Requirement: Analytics page with three panels
The system SHALL provide a `/analytics` frontend route that displays three analytics panels for a user-selected underlying and expiry: Max Pain Chart, GEX Chart, and OI Heatmap. The page SHALL auto-refresh data every 30 seconds. When the options poller is inactive (paper mode), each panel SHALL display a paper-mode placeholder instead of chart data.

#### Scenario: Analytics page renders in paper mode
- **WHEN** a user navigates to `/analytics` and `LIVE=0`
- **THEN** each panel shows a placeholder with text indicating live data is unavailable

#### Scenario: Analytics page auto-refreshes
- **WHEN** a user is viewing `/analytics` and 30 seconds elapse
- **THEN** all three panels silently re-fetch and re-render with updated data without a full page reload

#### Scenario: Underlying selector changes data
- **WHEN** a user selects "BANKNIFTY" from the underlying selector
- **THEN** all three panels re-fetch data for BANKNIFTY and re-render

---

### Requirement: Max Pain chart panel
The system SHALL render a bar chart showing option-writer pain (₹ value) at each strike, with a vertical reference line at the computed max-pain strike. The data source is `GET /api/v1/options/{underlying}/chain`. The chart SHALL highlight the current spot price with a second reference line in a distinct colour.

#### Scenario: Max pain marker shown at correct strike
- **WHEN** `max_pain = 22400` in the latest snapshot
- **THEN** a vertical reference line appears at strike 22400 on the chart

#### Scenario: Spot reference line shown
- **WHEN** `spot_price = 22513` in the snapshot
- **THEN** a vertical reference line in a distinct colour appears at 22513 on the chart

---

### Requirement: GEX chart panel
The system SHALL render a signed bar chart of net GEX per strike from `GET /api/v1/options/{underlying}/gex`. Bars with positive GEX SHALL be green; bars with negative GEX SHALL be red. An aggregate net GEX badge (in ₹ crore) SHALL be displayed above the chart.

#### Scenario: Positive GEX bars are green
- **WHEN** a strike has GEX > 0
- **THEN** its bar renders in green

#### Scenario: Negative GEX bars are red
- **WHEN** a strike has GEX < 0
- **THEN** its bar renders in red

#### Scenario: Net GEX badge shown
- **WHEN** the GEX endpoint returns `net_gex_cr = 3.42`
- **THEN** a badge reading "Net GEX: +₹3.42 Cr" is displayed above the chart

---

### Requirement: OI heatmap panel
The system SHALL render a 2D heatmap (strikes on y-axis, time snapshots on x-axis) showing total OI intensity per cell, fetched from `GET /api/v1/options/{underlying}/oi-history`. Cell colour intensity SHALL be proportional to OI normalised to the max OI in that time column. A PCR time-series line chart SHALL be displayed below the heatmap using the same time axis.

#### Scenario: High OI cell renders darker
- **WHEN** a strike has OI equal to the column max
- **THEN** that cell renders at full colour intensity

#### Scenario: PCR line chart shares time axis
- **WHEN** the heatmap has 40 time snapshots
- **THEN** the PCR line chart below it has exactly 40 data points on the same x-axis
