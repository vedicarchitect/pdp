## Context

The app has a portfolio slice and a partially-built `app/lib/features/dashboard/` slice wired at
`/dashboard` (first tab, `initialLocation`), but it deviates from house convention (no `Source`/mock
split) and stubs its richer content (an approximated running-sum "change" instead of vs-prev-close,
no global markets/commodities/VIX/FII-DII/sentiment sections). The `flutter-dashboard` OpenSpec
change is a stub (`proposal.md` + one-line `tasks.md`, no `design.md`/`specs/`).

Backend audit — real vs missing today:
- **Real now**: index spot LTP (`GET /api/v1/ltp?ids=13,25,51`, Redis `ltp:<sid>`), spot trend
  (SuperTrend via `/strangle/monitor`), positions (`/api/v1/portfolio/positions`), portfolio
  snapshot + live P&L (`/api/v1/portfolio/summary` + `/ws/portfolio`), today's realized P&L
  (`/journal/stats`), strategy chips (`GET /api/v1/strategies` `status`), margin
  (`/broker-sync/funds`, live-only).
- **Missing/mock**: India VIX (no endpoint; sid `21` already flows through the tick feed once
  subscribed), commodities (hardcoded in `pdp/intel/routes.py`), global market trend (nothing),
  FII/DII (`pdp/options/fii_dii.py` `StubFIIDIISource` → always `{available:false}`), sentiment
  (hardcoded in `pdp/intel/routes.py`), next-expiry (calendar logic exists in
  `pdp/instruments/expiry_calendar.py` but has no route).

Directive: use third-party Python libraries for the genuinely-missing data (global indices, news +
sentiment) rather than shipping fabricated values. A verification spike (Task 0) confirmed real data
from all four candidate libs in this venv: `yfinance` (index closes for `^DJI/^IXIC/^GSPC/^N225/^HSI/
^FTSE`), `nsepython` (`nse_fiidii()` — live daily FII/DII buy/sell/net), `feedparser` (Moneycontrol +
Economic Times RSS, real entries), `vaderSentiment` (real compound scores on headlines). No section
needs to ship honest-unavailable.

Product forks resolved with the user: commodities = **MCX INR via the existing Dhan feed** (not a
third-party lib — Dhan already carries this data); sentiment = **blend of news-headline scoring +
market internals**; **GIFT NIFTY omitted for v1** (no reliable free source).

## Goals / Non-Goals

**Goals:**
- Canonical home dashboard, house-convention (`Source`+mock, theme tokens, `domain/data/application/
  presentation` layering).
- Every value shown is real or honestly marked unavailable — no fabricated numbers in a real screen.
- Third-party/scrape-based data never touches the hot path (tick→WS p99 ≤ 50ms) — runs off a
  background poller into a cache; routes read cache only.
- One composed `GET /api/v1/dashboard` call for the Flutter home's initial paint; live deltas ride
  the existing `/ws/market` + `/ws/portfolio` sockets.
- Correct index change math (vs previous close), computed server-side.
- User-editable watchlist (local persistence for v1).

**Non-Goals:**
- GIFT NIFTY, or any other data source without a reliable free/paid feed already in the stack.
- A backend watchlist capability (cross-device sync) — noted as a future follow-up.
- New live order flows or portfolio mutations — this is a read/aggregation surface.

## Decisions

### 1. Third-party data runs off the hot path via a background poller + cache
`yfinance`/`nsepython`/`feedparser` are synchronous, slow, and scrape unofficial endpoints — they
must never touch the request path or the tick→WS hot path. A new `pdp/intel/poller.py` async task
(started in `main.py` lifespan, gated by `INTEL_ENABLED`) refreshes each source on its own interval
**inside a thread-pool executor** (`asyncio.to_thread` / `run_in_executor`), writing `{data, as_of}`
to Redis (key per source, e.g. `intel:global_indices`, `intel:news`, `intel:fii_dii`), falling back to
an in-process `app.state` dict if Redis is unavailable. Routes only ever read the cache — never call
a third-party lib inline on a request.

### 2. Canonical adapter pattern, mirrored from `pdp/options/fii_dii.py`
Each new source is a `@dataclass` DTO + `typing.Protocol` interface + `Stub` (returns `None`/empty) +
a gated concrete impl instantiated in `main.py` lifespan onto `app.state` (or constructed inside the
poller) + a defensive route read (`getattr(request.app.state, "x", Stub())`). A missing lib import or
a failed fetch degrades to honest `{"available": false}` — never raises 500 to the client and never
fabricates a value.

### 3. One composed `GET /api/v1/dashboard` aggregation endpoint
The Flutter home makes a single fast call (reads only cached/DB values — no synchronous third-party
calls in the request path) returning every section keyed with `available` + `as_of`. Live index ticks
and portfolio P&L continue to ride the **existing** `/ws/market` + `/ws/portfolio` sockets — no new
WS subscribe-sink is added for this change.

### 4. Correct change math: server computes `change`/`change_pct` from `prev_close`
Each index entry in `/api/v1/dashboard` (and a lighter `/api/v1/ltp` extension) carries `prev_close`
(previous session's close, from `market_bars`/EOD) alongside `ltp`; `change = ltp - prev_close`,
`change_pct = change / prev_close * 100`, computed server-side. The Flutter client seeds from this
`prev_close` and recomputes `change`/`change_pct` on every subsequent `/ws/market` tick — replacing
the existing slice's running-sum approximation.

### 5. Commodities = MCX INR via the Dhan feed (not a third-party lib)
Dhan already carries MCX commodity contracts (gold/crude/natgas/silver) over the same live feed used
for indices/options. Their security IDs are subscribed alongside the index/option subscriptions;
LTP + prior-close land in the same Redis `ltp:<sid>` cache the index cards already read. Unavailable
(feed not running, or sids not configured) → honest `{"available": false}` per commodity — never a
mock price.

### 6. Sentiment = blend of news-headline scoring + market internals
One 0–100 gauge combining: (a) `feedparser` RSS headlines scored with `vaderSentiment`'s compound
score (averaged over the latest N headlines, rescaled 0–100), and (b) market-internals signal already
computed elsewhere in the codebase (India VIX level, option PCR, advance/decline) — no new internals
computation, just read what already exists. Both sub-scores are exposed alongside the blended score so
the UI can show "why" (headline sentiment vs. VIX/PCR-derived internals). The fetched headlines also
feed the news list directly (no separate mock feed).

### 7. Watchlist persisted locally (shared_preferences) for v1
No backend watchlist capability exists; adding one is out of scope for this change. The Flutter
dashboard stores the user's symbol list in `shared_preferences` and resolves live quotes for those
symbols from the same index/LTP data path. Cross-device sync is a noted future backend follow-up, not
built here.

## Risks / Trade-offs

- **Third-party libs scrape unofficial endpoints** (Yahoo Finance, NSE) → can break or rate-limit
  without notice. Mitigated by: poller isolation (never blocks the hot path), per-source `Stub`
  fallback (a broken lib degrades that one section to `available:false`, not a 500), and a
  conservative poll interval (minutes, not seconds) since global indices/news don't need tick
  freshness.
- **`nsepython`'s FII/DII helper is a provisional/same-day figure** (NSE publishes a provisional
  figure same-day, finalized next day) → the `as_of` timestamp and a "provisional" flag on the
  response make this explicit rather than presenting it as final.
- **MCX commodity sids must be correct** (wrong sid → wrong or empty data) → resolved via the Dhan
  security master (same instrument-resolution path already used for indices/options), not
  hardcoded guesses.
- **Watchlist is local-only** → lost on reinstall/device switch; acceptable for v1, documented as a
  future backend sync point.

## Migration Plan

1. Backend: add deps (`yfinance`, `nsepython`, `feedparser`, `vaderSentiment`) via `uv add` (done),
   settings, adapter sources + Stubs, poller, routes, `main.py` wiring — all additive, no breaking
   changes to existing endpoints. `pdp/options/fii_dii.py` gets a real `NseFIIDIISource` alongside
   the existing `StubFIIDIISource` (default remains stub unless `INTEL_ENABLED` + lib present).
2. Rework `app/lib/features/dashboard/` in place to house convention; existing route (`/dashboard`,
   first tab) is unchanged so no navigation/link updates are needed elsewhere.
3. Verify: `task test` (backend), `flutter analyze && flutter test` (app), manual dashboard load
   with `task dev` running (real data) and with `USE_MOCK=true` (offline via mock source).

**Rollback:** `INTEL_ENABLED=false` reverts all new backend sections to `available:false` (existing
stub behavior) without touching the request path; the Flutter rework is a single feature directory
and can be reverted via git if needed.

## Open Questions

- Exact RSS feed set beyond Moneycontrol + Economic Times (confirmed working in the spike) — can add
  more Indian market business feeds during implementation without a design change.
- Whether to add a backend watchlist capability for cross-device sync — deferred; v1 is local-only.
