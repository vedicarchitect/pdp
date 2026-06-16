## ADDED Requirements

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

---

### Requirement: GEX REST endpoint
The system SHALL expose `GET /api/v1/options/{underlying}/gex?expiry=<ISO-date>` returning `{"underlying", "expiry", "spot_price", "lot_size", "per_strike": [{strike, gex}], "net_gex", "net_gex_cr", "snapshot_ts"}`. `net_gex_cr` SHALL be `net_gex / 1e9` rounded to 2 decimal places. The endpoint SHALL return HTTP 404 if no snapshot exists.

#### Scenario: GEX endpoint returns per-strike data
- **WHEN** `GET /api/v1/options/NIFTY/gex?expiry=2026-06-26` is called and a snapshot exists
- **THEN** HTTP 200 is returned with `per_strike` array sorted by strike ascending and `net_gex_cr` field

#### Scenario: GEX endpoint in paper mode
- **WHEN** the options poller is not active and `GET /api/v1/options/NIFTY/gex` is called
- **THEN** HTTP 200 is returned with `{"mode": "paper", "per_strike": [], "net_gex": 0}`

---

### Requirement: OI history REST endpoint
The system SHALL expose `GET /api/v1/options/{underlying}/oi-history?expiry=<ISO-date>&n=40` returning the last N snapshots for that expiry as `{"underlying", "expiry", "snapshots": [{"ts", "pcr", "strikes": [{"strike", "ce_oi", "pe_oi", "total_oi"}]}]}`. Snapshots SHALL be sorted oldest-first. `n` SHALL be capped at 200. The endpoint SHALL return HTTP 404 if no snapshot exists.

#### Scenario: OI history returns N snapshots oldest-first
- **WHEN** 50 snapshots exist and `?n=40` is requested
- **THEN** the 40 most recent snapshots are returned in ascending `ts` order

#### Scenario: OI history in paper mode
- **WHEN** the poller is not active and `/oi-history` is called
- **THEN** HTTP 200 is returned with `{"mode": "paper", "snapshots": []}`
