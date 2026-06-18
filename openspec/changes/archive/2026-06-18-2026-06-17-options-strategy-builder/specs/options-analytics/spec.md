## MODIFIED Requirements

### Requirement: Options router extended with payoff endpoints

The options analytics router SHALL include two new endpoints: `POST /api/v1/options/{underlying}/payoff` for on-demand payoff analysis, and `GET /api/v1/options/{underlying}/readymades` for readymade strategy templates. These endpoints SHALL be registered alongside existing analytics endpoints (chain, max-pain, pcr, gex, oi-history).

#### Scenario: Payoff endpoint coexists with analytics
- **WHEN** the API starts and all options endpoints are registered
- **THEN** both `/api/v1/options/NIFTY/max-pain` and `/api/v1/options/NIFTY/payoff` are accessible
