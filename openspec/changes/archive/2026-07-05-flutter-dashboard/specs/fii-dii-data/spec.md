## MODIFIED Requirements

### Requirement: Pluggable FII/DII data source

The system SHALL define a `FIIDIISource` protocol with a single `fetch(date) -> FIIDIIData | None`
method. The default implementation SHALL be `StubFIIDIISource` which always returns `None`. When
`INTEL_ENABLED` is set and `nsepython` is importable, a `NseFIIDIISource` implementation SHALL be
wired in place of the stub, fetching provisional daily FII/DII net-flow figures via `nsepython` (run
off the request path through the shared intel poller/cache — never invoked synchronously in a
request). A `GET /api/v1/options/fii-dii` endpoint SHALL call the configured source and return the
data if available, or `{"available": false}` if the source returns `None`. A `date` range
(yesterday + last 7 days) SHALL be resolvable for the dashboard's FII/DII panel.

#### Scenario: Stub source returns no data

- **WHEN** `StubFIIDIISource` is configured and `GET /api/v1/options/fii-dii` is called
- **THEN** HTTP 200 is returned with `{"available": false}`

#### Scenario: Concrete source returns data

- **WHEN** a concrete `FIIDIISource` is configured and returns valid FII/DII data for today
- **THEN** HTTP 200 is returned with `{"available": true, "data": {"fii_index_futures_net": ..., "dii_index_options_net": ..., ...}}`

#### Scenario: NseFIIDIISource is used when intel is enabled

- **WHEN** `INTEL_ENABLED` is true and `nsepython` is importable
- **THEN** `NseFIIDIISource` (backed by the intel poller cache) is wired instead of `StubFIIDIISource`, and its data carries an `as_of` timestamp reflecting the last successful poll

#### Scenario: A 7-day history is resolvable for the dashboard panel

- **WHEN** the dashboard requests FII/DII for the last 7 trading days
- **THEN** each day's net flow is returned where available, with missing days marked individually rather than failing the whole range

### Requirement: FII/DII frontend panel degrades gracefully

The frontend FII/DII panel SHALL only render when the API returns `available: true`. When
`available: false`, the panel SHALL be hidden entirely (no error message, no empty state — simply not
shown). This ensures the analytics page and the dashboard work cleanly regardless of whether a
FII/DII data source is configured.

#### Scenario: Panel hidden when no source

- **WHEN** the analytics page or dashboard loads and `/fii-dii` returns `{"available": false}`
- **THEN** no FII/DII panel or tab is visible to the user

#### Scenario: Panel visible when source configured

- **WHEN** the analytics page or dashboard loads and `/fii-dii` returns valid data
- **THEN** a FII/DII panel is visible showing net flows for FII and DII across index futures, index options, and stock futures
