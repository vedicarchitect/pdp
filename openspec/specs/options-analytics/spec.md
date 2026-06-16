# options-analytics Specification

## Purpose
Polls the Dhan option chain for configured underlyings, computes IV/Greeks/max-pain/PCR, persists per-expiry snapshots to MongoDB, and exposes them via REST and WebSocket.
## Requirements
### Requirement: Options chain ingest

The system SHALL resolve each configured underlying to its Dhan index security ID in the
`IDX_I` segment (`NIFTY=13`, `BANKNIFTY=25`, `FINNIFTY=27`, `MIDCPNIFTY=442`,
`SENSEX=51`) and SHALL enumerate available expiries via the Dhan `expiry_list` API. On a
`OPTIONS_POLL_INTERVAL_SECONDS` interval (default 30 s) during market hours (09:15–15:35
IST) the poller SHALL fetch the option chain for the nearest 3 expiries, issuing one
`option_chain` request per expiry with at least a 3-second gap between unique requests to
honour Dhan's rate limit. Each fetched expiry SHALL be stored as its own snapshot
document. Outside market hours the poller SHALL sleep without fetching. An on-demand
refresh SHALL be triggerable via `POST /api/v1/options/{underlying}/refresh`. If `LIVE=0`
or `DHAN_CLIENT_ID` is not set, the poller SHALL NOT start and REST endpoints SHALL
return an empty snapshot with `"mode":"paper"`.

#### Scenario: Poller fetches chain during market hours

- **WHEN** the system is live and current IST time is between 09:15 and 15:35
- **THEN** the poller fetches the option chain for the nearest 3 expiries of each
  configured underlying every `OPTIONS_POLL_INTERVAL_SECONDS` seconds and stores each
  expiry as its own document in MongoDB

#### Scenario: Correct index security ID is used

- **WHEN** the poller fetches the chain for `MIDCPNIFTY`
- **THEN** it requests Dhan with `under_security_id=442` and `under_exchange_segment="IDX_I"`,
  not the NIFTY-50 id

#### Scenario: Rate limit is honoured across expiries

- **WHEN** the poller fetches more than one expiry for an underlying in a single poll
- **THEN** consecutive `option_chain` requests are spaced at least 3 seconds apart

#### Scenario: Poller is idle outside market hours

- **WHEN** current IST time is before 09:15 or after 15:35
- **THEN** the poller sleeps and does not make any Dhan API requests

#### Scenario: On-demand refresh

- **WHEN** `POST /api/v1/options/NIFTY/refresh` is called
- **THEN** the poller fetches the NIFTY chain immediately (outside its regular schedule)
  and returns HTTP 202

#### Scenario: Paper mode returns empty snapshot

- **WHEN** `LIVE=0` or `DHAN_CLIENT_ID` is absent and `GET /api/v1/options/NIFTY/chain`
  is called
- **THEN** the response is HTTP 200 with `{"mode":"paper","strikes":[],"max_pain":null,"pcr":null}`

### Requirement: IV and Greeks computation

For every CE and PE strike in each snapshot the system SHALL populate implied volatility,
delta, gamma, theta, and vega. When the Dhan option-chain payload provides a non-null
`implied_volatility` and a complete `greeks` block for a side, the system SHALL use those
values directly. Otherwise the system SHALL compute them with `vollib` (Black-Scholes-
Merton) using the risk-free rate from `OPTIONS_RISK_FREE_RATE` (default 0.065) and
time-to-expiry derived as `(expiry_date − utcnow().date()).days / 365.0`. If T ≤ 0 the
system SHALL set all Greeks to 0 and skip IV computation. NaN IV values SHALL be clipped
to `[0.01, 5.0]`; NaN Greeks SHALL be replaced with 0.

#### Scenario: Dhan-provided greeks are used when present

- **WHEN** a snapshot strike has non-null `implied_volatility` and a complete `greeks`
  block from Dhan
- **THEN** the stored strike reflects those Dhan values without recomputation

#### Scenario: Greeks computed for ATM strike via fallback

- **WHEN** a snapshot for NIFTY is ingested with spot 22500 and a CE strike at 22500 with
  LTP 200 and 10 days to expiry and Dhan does not supply greeks for it
- **THEN** the stored document contains non-zero `iv`, `delta`, `gamma`, `theta`, `vega`
  for that CE strike computed via vollib

#### Scenario: Expired expiry Greeks zeroed

- **WHEN** the expiry date equals today and the current time is after 15:30 IST (T ≤ 0)
  and Dhan supplies no greeks
- **THEN** all Greek fields for every strike are stored as 0

#### Scenario: Deep OTM NaN handling

- **WHEN** the IV solver returns NaN for a deep OTM strike during fallback computation
- **THEN** the stored IV is clipped to 0.01 and the corresponding Greeks are stored as 0

### Requirement: Options chain MongoDB persistence

The system SHALL persist each polled snapshot as one document per `(underlying, expiry)` in the `option_chains` MongoDB collection. Each document SHALL contain `underlying` (str), `expiry` (ISO date str), `snapshot_ts` (UTC datetime), `spot_price` (float), `max_pain` (int strike), `pcr` (float), and `strikes` (array of strike objects). The collection SHALL have a TTL index on `snapshot_ts` controlled by `OPTIONS_CHAIN_TTL_DAYS` (default 7) and a compound index on `(underlying, expiry, snapshot_ts)`.

#### Scenario: Snapshot document written within 5 seconds of poll

- **WHEN** the poller fetches the NIFTY chain for expiry 2026-06-26
- **THEN** within 5 seconds a document with `underlying="NIFTY"`, `expiry="2026-06-26"` and matching `snapshot_ts` exists in `option_chains`

#### Scenario: Old snapshots expire automatically

- **WHEN** a snapshot document has `snapshot_ts` older than `OPTIONS_CHAIN_TTL_DAYS` days
- **THEN** MongoDB's TTL mechanism removes it automatically

### Requirement: Max-pain and PCR derivation

The system SHALL compute max-pain as the strike at which total option-writer pain (sum of ITM intrinsic value across all OI) is minimised. PCR SHALL be computed as `total_put_OI / total_call_OI` across all strikes for a given expiry. Both SHALL be stored in the snapshot document and returned in REST responses.

#### Scenario: Max-pain computed correctly

- **WHEN** a snapshot has OI distributed such that maximum writer pain is at strike 22400
- **THEN** `max_pain` field in the stored document equals 22400

#### Scenario: PCR computed correctly

- **WHEN** total put OI is 1 000 000 and total call OI is 800 000
- **THEN** `pcr` field equals 1.25

### Requirement: Options chain REST endpoints

The system SHALL expose:
- `GET /api/v1/options/{underlying}/chain?expiry=<ISO-date>` — returns the latest snapshot for that expiry; if `expiry` is omitted returns the nearest expiry.
- `GET /api/v1/options/{underlying}/max-pain?expiry=<ISO-date>` — returns `{"underlying":…,"expiry":…,"max_pain":…,"snapshot_ts":…}`.
- `GET /api/v1/options/{underlying}/pcr?expiry=<ISO-date>` — returns `{"underlying":…,"expiry":…,"pcr":…,"snapshot_ts":…}`.
- `POST /api/v1/options/{underlying}/refresh` — triggers an immediate fetch, returns HTTP 202.

All endpoints SHALL return HTTP 404 if no snapshot exists for the requested underlying/expiry.

#### Scenario: Chain endpoint returns latest snapshot

- **WHEN** `GET /api/v1/options/NIFTY/chain?expiry=2026-06-26` is called and a snapshot exists
- **THEN** HTTP 200 is returned with the full strikes array, `max_pain`, `pcr`, and `snapshot_ts`

#### Scenario: Chain endpoint with missing expiry

- **WHEN** `GET /api/v1/options/NIFTY/chain?expiry=2026-06-26` is called and no snapshot exists for that expiry
- **THEN** HTTP 404 is returned

#### Scenario: Max-pain endpoint

- **WHEN** `GET /api/v1/options/NIFTY/max-pain?expiry=2026-06-26` is called
- **THEN** HTTP 200 with `{"underlying":"NIFTY","expiry":"2026-06-26","max_pain":22400,"snapshot_ts":"..."}`

#### Scenario: PCR endpoint

- **WHEN** `GET /api/v1/options/NIFTY/pcr?expiry=2026-06-26` is called
- **THEN** HTTP 200 with `{"underlying":"NIFTY","expiry":"2026-06-26","pcr":1.25,"snapshot_ts":"..."}`

### Requirement: GEX computation

The system SHALL provide a `compute_gex(strikes, lot_size, spot)` function in `src/pdp/options/analytics.py` that returns a dict with `per_strike` (list of `{strike, gex}`) and `net_gex` (sum across all strikes). GEX per strike SHALL be computed as `(ce_gamma × ce_oi - pe_gamma × pe_oi) × lot_size × spot²`. Strikes where both CE and PE gamma are zero or absent SHALL contribute 0 to GEX.

#### Scenario: GEX computed correctly for single strike

- **WHEN** a strike has `ce_gamma=0.002`, `ce_oi=100000`, `pe_gamma=0.001`, `pe_oi=80000`, `lot_size=75`, `spot=22500`
- **THEN** `gex = (0.002 × 100000 - 0.001 × 80000) × 75 × 22500² = (200 - 80) × 75 × 506250000 = 4556250000000`

#### Scenario: Missing gamma fields default to zero

- **WHEN** a strike has no `gamma` field in its CE or PE dict
- **THEN** that side contributes 0 gamma to the GEX formula and no KeyError is raised

#### Scenario: Net GEX is sum of all strike GEX

- **WHEN** three strikes have GEX values 100, -50, 200
- **THEN** `net_gex = 250`

### Requirement: GEX REST endpoint

The system SHALL expose `GET /api/v1/options/{underlying}/gex?expiry=<ISO-date>` returning `{"underlying", "expiry", "spot_price", "lot_size", "per_strike": [{strike, gex}], "net_gex", "net_gex_cr", "snapshot_ts"}`. `net_gex_cr` SHALL be `net_gex / 1e9` rounded to 2 decimal places. The endpoint SHALL return HTTP 404 if no snapshot exists.

#### Scenario: GEX endpoint returns per-strike data

- **WHEN** `GET /api/v1/options/NIFTY/gex?expiry=2026-06-26` is called and a snapshot exists
- **THEN** HTTP 200 is returned with `per_strike` array sorted by strike ascending and `net_gex_cr` field

#### Scenario: GEX endpoint in paper mode

- **WHEN** the options poller is not active and `GET /api/v1/options/NIFTY/gex` is called
- **THEN** HTTP 200 is returned with `{"mode": "paper", "per_strike": [], "net_gex": 0}`

### Requirement: OI history REST endpoint

The system SHALL expose `GET /api/v1/options/{underlying}/oi-history?expiry=<ISO-date>&n=40` returning the last N snapshots for that expiry as `{"underlying", "expiry", "snapshots": [{"ts", "pcr", "strikes": [{"strike", "ce_oi", "pe_oi", "total_oi"}]}]}`. Snapshots SHALL be sorted oldest-first. `n` SHALL be capped at 200. The endpoint SHALL return HTTP 404 if no snapshot exists.

#### Scenario: OI history returns N snapshots oldest-first

- **WHEN** 50 snapshots exist and `?n=40` is requested
- **THEN** the 40 most recent snapshots are returned in ascending `ts` order

#### Scenario: OI history in paper mode

- **WHEN** the poller is not active and `/oi-history` is called
- **THEN** HTTP 200 is returned with `{"mode": "paper", "snapshots": []}`

### Requirement: Options WebSocket endpoint

The system SHALL expose `/ws/options`. After connecting, a client SHALL send `{"action":"subscribe","underlying":"NIFTY","expiry":"2026-06-26"}` to receive snapshot push events. Each client SHALL have a dedicated queue bounded at 20 messages; when full the oldest message SHALL be dropped and `ws_options_client_lagging` SHALL be logged. On each new snapshot for the subscribed `(underlying, expiry)` the server SHALL push the full snapshot JSON.

#### Scenario: Client receives snapshot after subscribe

- **WHEN** a client connects and subscribes to NIFTY 2026-06-26 and a new snapshot arrives
- **THEN** the client receives the full snapshot JSON within 2 seconds of the snapshot being stored

#### Scenario: Slow client drop-oldest

- **WHEN** a client's pending queue reaches 20 messages before they are consumed
- **THEN** the oldest queued message is dropped and `ws_options_client_lagging` is logged

