## Context

PDP's options analytics module (`src/pdp/options/analytics.py`) currently computes:
- Max pain from option chain OI
- Put-Call Ratio (PCR) from OI
- Gamma Exposure (GEX) from Greeks
- OI history from `option_chains` snapshots

The option chain data is stored in MongoDB (`option_chains` collection) as periodic snapshots from the `OptionsChainPoller`. Historical option OHLCV bars are in `option_bars` (intraday) and `expired_option_bars` (post-expiry archive). These collections likely contain IV data per bar, but this needs verification during implementation.

FII/DII data is not currently ingested — there is no source configured. NSE publishes daily FII/DII derivative statistics, but scraping is fragile and rate-limited. The design uses a pluggable interface so a source can be added without changing the analytics layer.

## Goals / Non-Goals

**Goals:**
- Add OI-based market structure signals (buildup classification, multi-strike OI change).
- Add IV context signals (IV rank, IV percentile, straddle premium history).
- Make FII/DII data integration pluggable with graceful degradation.
- Expand the analytics frontend with new panels.

**Non-Goals:**
- Historical OI buildup backtesting (future enhancement).
- Options flow analysis (large trade detection) — requires tick-level data we don't have.
- IV surface / skew analysis — future proposal.
- Automated trading signals from OI/IV — strategy layer, not analytics.

## Decisions

### D1: OI buildup classification uses price + OI deltas

The standard 2×2 classification matrix:

| Price Δ | OI Δ   | Classification    |
|---------|--------|-------------------|
| ↑       | ↑      | Long Buildup      |
| ↓       | ↑      | Short Buildup     |
| ↑       | ↓      | Short Covering    |
| ↓       | ↓      | Long Unwinding    |

Deltas are computed from the latest two `option_chains` snapshots for each strike. The endpoint returns classification per strike for the current expiry.

```python
def classify_oi_buildup(
    current: dict,   # {strike: {price, oi}}
    previous: dict,  # {strike: {price, oi}}
) -> list[dict]:    # [{strike, classification, price_change, oi_change, oi_change_pct}]
```

### D2: Multi-strike OI series from option_chains snapshots

Query `option_chains` collection for the last N snapshots (configurable via `interval` param: 5m, 15m, 1H, 1D), extract OI per strike, compute change. Return as a time-series for the frontend to render as a multi-line chart.

### D3: ATM straddle price from intraday chain snapshots

ATM is the strike closest to spot. Straddle premium = ATM CE premium + ATM PE premium. Query today's `option_chains` snapshots, compute straddle premium at each timestamp. Return as `[{timestamp, premium, ce_premium, pe_premium}]`.

### D4: IV rank/percentile from historical bars

IV rank = `(current_iv - min_iv_N_days) / (max_iv_N_days - min_iv_N_days)` where N defaults to 252 (1 year trading days). IV percentile = percentage of days where close IV was below current IV, over N days.

Data source: `option_bars` (recent) + `expired_option_bars` (historical). Use ATM strike's IV as the representative IV for each day.

**Pre-implementation verification needed**: Confirm that `option_bars` documents contain an `iv` field. If not, IV must be computed from premium + spot + Greeks (Black-Scholes inversion) at query time.

### D5: FII/DII pluggable interface with stub

```python
class FIIDIISource(Protocol):
    async def fetch(self, date: date) -> FIIDIIData | None: ...

@dataclass
class FIIDIIData:
    date: date
    fii_index_futures_net: float
    fii_index_options_net: float
    fii_stock_futures_net: float
    dii_index_futures_net: float
    dii_index_options_net: float
    dii_stock_futures_net: float

class StubFIIDIISource:
    async def fetch(self, date: date) -> None:
        return None  # No data available
```

The route checks the return value — if `None`, returns `{"available": false}`. The frontend hides the FII/DII panel when `available` is false.

### D6: Frontend panels layout

The existing analytics page is expanded with tabs or additional card sections:

```
┌───────────────────────────────────────────┐
│ Analytics — NIFTY                         │
├───────────────────────────────────────────┤
│ [Max Pain] [GEX] [PCR] [OI Buildup]      │  ← tab row
│ [Straddle] [IV Rank] [OI Change] [FII/DII]│
├───────────────────────────────────────────┤
│ (active panel content)                    │
└───────────────────────────────────────────┘
```

## Risks / Trade-offs

- **IV data availability**: `option_bars` may not store IV directly. If not, Black-Scholes inversion is needed at query time, which adds computation. Pre-implementation: run a MongoDB query to check field presence.
- **FII/DII data source**: NSE website scraping is fragile. Ship as stub; add a concrete source later when a reliable feed is identified. The frontend degrades cleanly.
- **Snapshot frequency**: OI buildup quality depends on snapshot frequency (currently every chain poll interval). If polls are 5 minutes apart, intraday buildup classification has 5-minute granularity.

## Migration Plan

1. Add OI buildup and straddle history functions to `analytics.py`.
2. Add IV rank/percentile function (verify IV field first).
3. Create `fii_dii.py` with interface + stub.
4. Add new endpoints to `routes.py`.
5. Write/extend tests.
6. Build frontend panels.
7. Integrate panels into analytics route.

## Open Questions

- **IV field in `option_bars`**: Verify before implementation. If absent, decide: compute at query time, or add IV computation to the bar writer pipeline (separate change).
- **FII/DII source**: NSE scraping? Third-party API? Or user-uploaded CSV? Defer decision — ship stub, add source later.
