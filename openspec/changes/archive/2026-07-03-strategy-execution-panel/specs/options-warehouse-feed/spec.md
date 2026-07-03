## MODIFIED Requirements

### Requirement: Options chain poller start condition

The options chain poller SHALL start whenever `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are present and
`OPTIONS_POLLER_ENABLED` is true, independent of the `LIVE` flag, so that paper sessions receive realtime
chain data (Greeks, OI, PCR). The poller is read-only market data and MUST NOT place or modify orders.
When credentials are absent or `OPTIONS_POLLER_ENABLED` is false, the poller SHALL NOT start and chain
REST endpoints SHALL return an empty `{"mode":"paper"}` snapshot.

#### Scenario: Poller runs in paper with credentials

- **WHEN** `LIVE` is unset but `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` are set and `OPTIONS_POLLER_ENABLED` is true
- **THEN** the options poller starts and persists `option_chains` snapshots during market hours

#### Scenario: Poller disabled by flag

- **WHEN** `OPTIONS_POLLER_ENABLED` is false
- **THEN** the poller does not start regardless of credentials

#### Scenario: Poller skipped without credentials

- **WHEN** `DHAN_CLIENT_ID` or `DHAN_ACCESS_TOKEN` is absent
- **THEN** the poller does not start and `GET /api/v1/options/NIFTY/chain` returns `{"mode":"paper", ...}`
