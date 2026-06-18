## MODIFIED Requirements

### Requirement: Portfolio route displays holdings and positions

The `/portfolio` route SHALL fetch data from `GET /api/v1/portfolio/holdings` and `GET /api/v1/portfolio/positions` and display them in two `DataTable` sections within `Card` containers. A summary section at the top SHALL show total P&L, total investment value, and day change from `GET /api/v1/portfolio/summary` (if available; degrade gracefully if endpoint returns 404).

#### Scenario: Portfolio page loads with holdings data
- **WHEN** a user navigates to `/portfolio` and the API returns 5 holdings
- **THEN** a "Holdings" card with a DataTable of 5 rows is displayed, showing columns: Symbol, Qty, Avg Price, LTP, P&L, P&L %

#### Scenario: Portfolio page loads with positions data
- **WHEN** a user navigates to `/portfolio` and the API returns 3 open positions
- **THEN** a "Positions" card with a DataTable of 3 rows is displayed, showing columns: Symbol, Side, Qty, Entry Price, LTP, P&L

#### Scenario: Portfolio page handles empty state
- **WHEN** a user navigates to `/portfolio` and the API returns zero holdings and zero positions
- **THEN** both DataTables show "No holdings" and "No open positions" empty messages respectively

#### Scenario: Portfolio page handles API error gracefully
- **WHEN** the portfolio API returns an error
- **THEN** an error card is displayed with a retry button
