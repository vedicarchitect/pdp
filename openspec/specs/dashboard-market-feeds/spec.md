# dashboard-market-feeds Specification

## Purpose
Backend data feeds that power the dashboard's non-portfolio sections — global indices, MCX
commodities, India VIX, next-expiry, news/sentiment — refreshed off the hot path by a background
poller and served to request handlers only from cache, then composed into a single aggregation
endpoint for the dashboard.

## Requirements

### Requirement: Off-hot-path third-party data poller
Third-party/scrape-based data sources (global market indices, news, sentiment) SHALL be refreshed by
a background poller task, gated by `INTEL_ENABLED`, that runs each synchronous library call inside a
thread-pool executor and writes `{data, as_of}` to a cache (Redis, falling back to an in-process
cache if Redis is unavailable). Request-handling routes SHALL read only from this cache and SHALL
NEVER invoke a third-party library synchronously within a request.

#### Scenario: A request never blocks on a third-party call
- **WHEN** `GET /api/v1/dashboard` (or any intel route) is called
- **THEN** the response is served from the cache and completes without invoking `yfinance`/`nsepython`/`feedparser` inline

#### Scenario: A stale cache still serves honestly
- **WHEN** the poller has not yet completed its first refresh, or its last refresh failed
- **THEN** the route returns `{"available": false}` for that section rather than blocking or fabricating data

### Requirement: Global market indices endpoint
`GET /api/v1/intel/global-indices` SHALL return the latest close/change for Dow Jones, Nasdaq, S&P
500, Nikkei 225, Hang Seng, and FTSE 100, sourced via `yfinance` through the poller cache, each with
its own `available` flag and a shared `as_of` for the fetch.

#### Scenario: Global indices are returned when the poller has fresh data
- **WHEN** the poller has successfully fetched within its configured interval
- **THEN** `GET /api/v1/intel/global-indices` returns `available: true` with close/change per index and an `as_of` timestamp

#### Scenario: A single index's fetch failure does not blank the whole response
- **WHEN** one index ticker fails to resolve during a poll cycle but others succeed
- **THEN** the failed index is returned with `available: false` while the others return their real values

### Requirement: MCX commodities endpoint (Dhan feed, not third-party)
`GET /api/v1/intel/commodities` SHALL return MCX gold/crude/natgas/silver LTP and change in INR,
sourced from the existing Dhan live feed's Redis LTP cache (the same `ltp:<sid>` path used by
indices/options) — not from a third-party library. Each commodity SHALL degrade to
`available: false` independently if its security id is unconfigured or has no fresh tick.

#### Scenario: Commodities reflect live Dhan feed prices
- **WHEN** MCX commodity security ids are subscribed and the feed is running
- **THEN** `GET /api/v1/intel/commodities` returns real LTP/change in INR for each configured commodity

#### Scenario: Commodities degrade honestly when the feed is down
- **WHEN** the Dhan feed is not running or a commodity's security id has no cached tick
- **THEN** that commodity's entry returns `available: false` — never a mock/hardcoded price

### Requirement: India VIX endpoint
`GET /api/v1/intel/vix` SHALL return the current India VIX level and change, sourced from the
existing tick feed's LTP cache for the configured VIX security id.

#### Scenario: VIX is returned from the live feed
- **WHEN** the VIX security id has a fresh cached tick
- **THEN** `GET /api/v1/intel/vix` returns `available: true` with the current level and change

### Requirement: Next-expiry endpoint
`GET /api/v1/intel/next-expiry` SHALL return the upcoming expiry date per configured index
(NIFTY/BANKNIFTY/SENSEX), wrapping the existing `pdp/instruments/expiry_calendar.py` resolution
logic behind a route (previously a library with no endpoint).

#### Scenario: Next expiry is resolved per index
- **WHEN** `GET /api/v1/intel/next-expiry` is called
- **THEN** each configured index's next expiry date is returned using the existing expiry calendar

### Requirement: News and blended sentiment endpoint
`GET /api/v1/intel/news` SHALL return recent market headlines fetched via `feedparser` from
configured RSS feeds. `GET /api/v1/intel/sentiment` SHALL return a blended 0-100 sentiment score
combining (a) a `vaderSentiment` compound score averaged over recent headlines and (b) existing
market-internals signals already computed elsewhere (India VIX level, option PCR, advance/decline),
exposing both sub-scores alongside the blend.

#### Scenario: News returns real headlines
- **WHEN** the poller has successfully fetched from at least one configured RSS feed
- **THEN** `GET /api/v1/intel/news` returns `available: true` with real headline/source/published_at entries

#### Scenario: Sentiment exposes its sub-components
- **WHEN** `GET /api/v1/intel/sentiment` returns `available: true`
- **THEN** the response includes the blended score plus the news-headline sub-score and the market-internals sub-score separately

#### Scenario: Sentiment degrades when both inputs are unavailable
- **WHEN** neither headlines nor market-internals signals can be computed
- **THEN** `GET /api/v1/intel/sentiment` returns `available: false` rather than a fabricated score

### Requirement: Composed dashboard aggregation endpoint
`GET /api/v1/dashboard` SHALL compose index spot+change (with `prev_close`), global indices,
commodities, VIX, next-expiry, FII/DII, sentiment+news, portfolio snapshot, today's realized P&L,
margin, and strategy-status chips into one response, each section keyed with its own `available` +
`as_of`, reading only from caches/DB (no synchronous third-party calls in the request path).

#### Scenario: One call seeds the whole dashboard
- **WHEN** `GET /api/v1/dashboard` is called
- **THEN** the response contains every section (present or `available: false`) and completes without any blocking third-party call
