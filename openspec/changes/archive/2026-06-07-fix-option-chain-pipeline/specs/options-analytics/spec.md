## MODIFIED Requirements

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
