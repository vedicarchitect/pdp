## MODIFIED Requirements

### Requirement: Portfolio REST endpoints
The system SHALL expose:
- `GET /api/v1/portfolio/positions` — returns all positions from PG (with the latest `unrealized_pnl`).
- `GET /api/v1/portfolio/summary` — returns `{"total_unrealized_pnl": float, "total_realized_pnl": float, "day_pnl": float, "open_positions": int, "mode": "paper|live"}`.

Both endpoints SHALL return HTTP 200 with an empty positions array if no positions exist. Both endpoints SHALL read from the PG `positions` table (not the in-memory cache) for consistency. Mode filtering is not supported as the `positions` table has no `mode` column; the `mode` field in the summary response is derived from the `LIVE` setting.

`realized_pnl` values returned by these endpoints SHALL reflect the corrected short-position accounting: for any position closed from a multi-leg short, `realized_pnl` SHALL equal `(correct_weighted_avg - close_price) * closed_qty` with no sign inversion.

#### Scenario: Positions endpoint returns open positions
- **WHEN** `GET /api/v1/portfolio/positions` is called and two open positions exist
- **THEN** HTTP 200 is returned with a JSON array containing both positions including `unrealized_pnl`, `realized_pnl`, `avg_price`, `net_qty`, and `updated_at`

#### Scenario: Summary endpoint
- **WHEN** `GET /api/v1/portfolio/summary` is called and positions have total unrealized P&L of ₹5000 and realized P&L of ₹1200
- **THEN** HTTP 200 is returned with `{"total_unrealized_pnl": 5000.0, "total_realized_pnl": 1200.0, "day_pnl": 6200.0, "open_positions": 2, "mode": "paper"}`

#### Scenario: Empty portfolio
- **WHEN** `GET /api/v1/portfolio/positions` is called and no positions exist
- **THEN** HTTP 200 is returned with `{"positions": [], "count": 0}`

#### Scenario: Short close realized P&L is correct
- **WHEN** a 4-leg short (total 325 units, weighted avg ≈ 85.30) is closed by BUY 325 @ 96.52
- **THEN** `GET /api/v1/portfolio/summary` returns `total_realized_pnl ≈ -3645` (not +37256 or any sign-inverted value)
