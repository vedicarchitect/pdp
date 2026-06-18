## ADDED Requirements

### Requirement: Pluggable FII/DII data source

The system SHALL define a `FIIDIISource` protocol with a single `fetch(date) -> FIIDIIData | None` method. The default implementation SHALL be `StubFIIDIISource` which always returns `None`. A `GET /api/v1/options/fii-dii` endpoint SHALL call the configured source and return the data if available, or `{"available": false}` if the source returns `None`.

#### Scenario: Stub source returns no data
- **WHEN** `StubFIIDIISource` is configured and `GET /api/v1/options/fii-dii` is called
- **THEN** HTTP 200 is returned with `{"available": false}`

#### Scenario: Concrete source returns data
- **WHEN** a concrete `FIIDIISource` is configured and returns valid FII/DII data for today
- **THEN** HTTP 200 is returned with `{"available": true, "data": {fii_index_futures_net: ..., dii_index_options_net: ..., ...}}`

---

### Requirement: FII/DII frontend panel degrades gracefully

The frontend FII/DII panel SHALL only render when the API returns `available: true`. When `available: false`, the panel SHALL be hidden entirely (no error message, no empty state — simply not shown). This ensures the analytics page works cleanly regardless of whether a FII/DII data source is configured.

#### Scenario: Panel hidden when no source
- **WHEN** the analytics page loads and `/fii-dii` returns `{"available": false}`
- **THEN** no FII/DII panel or tab is visible to the user

#### Scenario: Panel visible when source configured
- **WHEN** the analytics page loads and `/fii-dii` returns valid data
- **THEN** a FII/DII panel is visible showing net flows for FII and DII across index futures, index options, and stock futures
