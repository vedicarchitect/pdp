## ADDED Requirements

### Requirement: Options chain ingest

The system SHALL poll the Dhan `/v2/optionchain` REST endpoint for each configured underlying on a `OPTIONS_POLL_INTERVAL_SECONDS` interval (default 30 s) during market hours (09:15–15:35 IST). Each poll SHALL fetch all strikes and all available weekly expiries up to the nearest 3. Outside market hours the poller SHALL sleep without fetching. An on-demand refresh SHALL be triggerable via `POST /api/v1/options/{underlying}/refresh`. If `LIVE=0` or `DHAN_CLIENT_ID` is not set, the poller SHALL NOT start and REST endpoints SHALL return an empty snapshot with `"mode":"paper"`.

#### Scenario: Poller fetches chain during market hours

- **WHEN** the system is live and current IST time is between 09:15 and 15:35
- **THEN** the poller fetches the Dhan options chain for each configured underlying every `OPTIONS_POLL_INTERVAL_SECONDS` seconds and stores each result in MongoDB

#### Scenario: Poller is idle outside market hours

- **WHEN** current IST time is before 09:15 or after 15:35
- **THEN** the poller sleeps and does not make any Dhan API requests

#### Scenario: On-demand refresh

- **WHEN** `POST /api/v1/options/NIFTY/refresh` is called
- **THEN** the poller fetches the NIFTY chain immediately (outside its regular schedule) and returns HTTP 202

#### Scenario: Paper mode returns empty snapshot

- **WHEN** `LIVE=0` or `DHAN_CLIENT_ID` is absent and `GET /api/v1/options/NIFTY/chain` is called
- **THEN** the response is HTTP 200 with `{"mode":"paper","strikes":[],"max_pain":null,"pcr":null}`

### Requirement: IV and Greeks computation

The system SHALL compute implied volatility, delta, gamma, theta, and vega for every CE and PE strike in each snapshot using `py_vollib_vectorized`. Computation SHALL use the Black-Scholes model with risk-free rate from `OPTIONS_RISK_FREE_RATE` (default 0.065). Time-to-expiry SHALL be derived as `(expiry_date − utcnow().date()).days / 365.0`. If T ≤ 0 the system SHALL set all Greeks to 0 and skip IV computation. NaN IV values SHALL be clipped to `[0.01, 5.0]`; NaN Greeks SHALL be replaced with 0.

#### Scenario: Greeks computed for ATM strike

- **WHEN** a snapshot for NIFTY is ingested with spot 22500 and a CE strike at 22500 with LTP 200 and 10 days to expiry
- **THEN** the stored document contains non-zero `iv`, `delta`, `gamma`, `theta`, `vega` for that CE strike

#### Scenario: Expired expiry Greeks zeroed

- **WHEN** the expiry date equals today and the current time is after 15:30 IST (T ≤ 0)
- **THEN** all Greek fields for every strike are stored as 0

#### Scenario: Deep OTM NaN handling

- **WHEN** the IV solver returns NaN for a deep OTM strike
- **THEN** the stored IV is clipped to 0.01 and the corresponding Greeks are stored as 0

### Requirement: Options chain MongoDB persistence

The system SHALL persist each polled snapshot as one document per `(underlying, expiry)` in the `options_chain` MongoDB collection. Each document SHALL contain `underlying` (str), `expiry` (ISO date str), `snapshot_ts` (UTC datetime), `spot_price` (float), `max_pain` (int strike), `pcr` (float), and `strikes` (array of strike objects). The collection SHALL have a TTL index of 7 days on `snapshot_ts` and a compound index on `(underlying, expiry, snapshot_ts)`.

#### Scenario: Snapshot document written within 5 seconds of poll

- **WHEN** the poller fetches the NIFTY chain for expiry 2026-06-26
- **THEN** within 5 seconds a document with `underlying="NIFTY"`, `expiry="2026-06-26"` and matching `snapshot_ts` exists in `options_chain`

#### Scenario: Old snapshots expire automatically

- **WHEN** a snapshot document has `snapshot_ts` older than 7 days
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

### Requirement: Options WebSocket endpoint

The system SHALL expose `/ws/options`. After connecting, a client SHALL send `{"action":"subscribe","underlying":"NIFTY","expiry":"2026-06-26"}` to receive snapshot push events. Each client SHALL have a dedicated queue bounded at 20 messages; when full the oldest message SHALL be dropped and `ws_options_client_lagging` SHALL be logged. On each new snapshot for the subscribed `(underlying, expiry)` the server SHALL push the full snapshot JSON.

#### Scenario: Client receives snapshot after subscribe

- **WHEN** a client connects and subscribes to NIFTY 2026-06-26 and a new snapshot arrives
- **THEN** the client receives the full snapshot JSON within 2 seconds of the snapshot being stored

#### Scenario: Slow client drop-oldest

- **WHEN** a client's pending queue reaches 20 messages before they are consumed
- **THEN** the oldest queued message is dropped and `ws_options_client_lagging` is logged
