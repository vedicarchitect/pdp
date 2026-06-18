## ADDED Requirements

### Requirement: Backtest routes registered in main.py

The existing `src/pdp/backtest/routes.py` router SHALL be registered in `src/pdp/main.py` so that read-only backtest result endpoints are accessible via the API. This includes any existing `GET` endpoints for listing and viewing past backtest results.

#### Scenario: Backtest routes are accessible
- **WHEN** the API starts
- **THEN** `GET /api/v1/backtests` (if defined) is accessible and returns HTTP 200

---

### Requirement: Backtest run endpoint

The backtest router SHALL include a `POST /api/v1/backtests/run` endpoint that accepts an options strategy configuration and executes the backtest. When the job runner (proposal #5) is available, this endpoint SHALL submit the backtest as an async job instead of running synchronously.

#### Scenario: Synchronous execution before job runner
- **WHEN** `POST /api/v1/backtests/run` is called and the job runner is not yet available
- **THEN** the backtest runs synchronously and results are returned in the response body
