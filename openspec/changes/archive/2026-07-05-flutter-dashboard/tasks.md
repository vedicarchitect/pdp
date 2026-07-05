## 0. Verification spike
- [x] 0.1 Confirm `yfinance`, `nsepython`, `feedparser`, `vaderSentiment` return real data in the
      backend venv; record which sections (if any) must ship as honest-unavailable (none — all four
      confirmed real data)

## 1. OpenSpec artifacts
- [x] 1.1 Write `design.md` (context, goals/non-goals, 7 decisions, risks, migration plan, open questions)
- [x] 1.2 Write `specs/flutter-dashboard/spec.md` (NEW capability)
- [x] 1.3 Write `specs/dashboard-market-feeds/spec.md` (NEW capability)
- [x] 1.4 Write `specs/fii-dii-data/spec.md` (MODIFIED capability)
- [x] 1.5 Rewrite `tasks.md` into grouped checkboxes (this file)
- [x] 1.6 `openspec validate flutter-dashboard --strict` passes

## 2. Backend: deps, settings, adapter sources
- [x] 2.1 `uv add yfinance nsepython feedparser vaderSentiment` (done — pyproject.toml + uv.lock updated)
- [x] 2.2 `pdp/settings.py`: add `INTEL_ENABLED`, per-source poll intervals
      (`INTEL_GLOBAL_INDICES_POLL_SECONDS`, `INTEL_NEWS_POLL_SECONDS`, `INTEL_FII_DII_POLL_SECONDS`),
      RSS feed URL list (`INTEL_NEWS_FEED_URLS`), MCX commodity security ids
      (`MCX_GOLD_SECURITY_ID`/`MCX_CRUDE_SECURITY_ID`/`MCX_NATGAS_SECURITY_ID`/`MCX_SILVER_SECURITY_ID`),
      `VIX_SECURITY_ID` (default `"21"`)
- [x] 2.3 `pdp/intel/sources/global_market.py`: `GlobalIndexData` dataclass + `GlobalMarketSource`
      Protocol + `YfinanceGlobalMarketSource` (wraps `yfinance.download`/`fast_info` in
      `asyncio.to_thread`) + `StubGlobalMarketSource`
- [x] 2.4 `pdp/intel/sources/news.py`: `NewsArticle` dataclass + `NewsSource` Protocol +
      `FeedparserNewsSource` (feedparser over configured RSS urls, in `asyncio.to_thread`) +
      `StubNewsSource`
- [x] 2.5 `pdp/intel/sources/sentiment.py`: `SentimentData` dataclass (blended score + news sub-score
      + internals sub-score) + `SentimentSource` Protocol + `BlendedSentimentSource` (vaderSentiment
      over cached headlines + existing VIX/PCR-shaped internals) + `StubSentimentSource`
- [x] 2.6 `pdp/options/fii_dii.py`: add `NseFIIDIISource` (nsepython `nse_fiidii()` in
      `asyncio.to_thread`) + range/history fetch (yesterday + last 7 days); keep
      `StubFIIDIISource` as the fallback default

## 3. Backend: poller, cache, routes, wiring
- [x] 3.1 `pdp/intel/poller.py`: async task refreshing each source on its own interval inside a
      thread-pool executor, writing `{data, as_of}` per source key to Redis (fallback: in-process
      `app.state` dict if Redis unavailable)
- [x] 3.2 `pdp/intel/routes.py`: replace mock `/commodities` and `/sentiment`; add `/global-indices`,
      `/news`, `/vix`, `/next-expiry`; all routes read cache/Redis only (no third-party calls inline)
- [x] 3.3 `GET /api/v1/dashboard` composed endpoint (`pdp/intel/dashboard_routes.py`): index
      spot+prev_close+change, global indices, commodities, VIX, next-expiry, FII/DII,
      sentiment+news, portfolio snapshot, today's realized P&L, margin, strategy-status chips —
      each section with `available`(+`as_of` where applicable)
- [x] 3.4 `/api/v1/dashboard`'s `indices` section includes `prev_close` per index (from `market_bars`
      1D bar) so client-side change math is vs-prev-close, not running-sum
- [x] 3.5 `pdp/main.py`: instantiate real sources gated on `INTEL_ENABLED` + successful lib import
      (else Stub), store on `app.state`, start the poller in `lifespan`, `include_router` new routes
- [x] 3.6 Auto-subscribe configured MCX commodity security ids once at startup (idempotent —
      persisted `Subscription` rows auto-restore on restart); `GET /api/v1/intel/commodities` and
      the dashboard endpoint read their LTP from the existing Redis `ltp:<sid>` cache
- [x] 3.7 Wrap `pdp/instruments/expiry_calendar.py` in the `/next-expiry` route (and the dashboard
      endpoint) for NIFTY/BANKNIFTY/SENSEX

## 4. Backend tests
- [x] 4.1 Unit tests for each source with the underlying lib mocked (success + failure → Stub-shaped
      degradation) — `tests/intel/test_sources.py` (14 tests)
- [x] 4.2 Route tests: `/api/v1/dashboard`, `/global-indices`, `/news`, `/sentiment`, `/vix`,
      `/next-expiry`, `/options/fii-dii(+/history)` — both available and `available:false` paths —
      `tests/intel/test_routes.py` (13 tests) + additions to `tests/options/test_routes.py`
- [x] 4.3 Poller test: confirms it runs sync lib calls off the event loop (executor) and writes
      `{data, as_of}` to the cache — `tests/intel/test_poller.py` (5 tests). Full suite run + a
      stash-based baseline diff confirmed zero regressions (31 pre-existing/environment-dependent
      failures unrelated to this change, same set on baseline).

## 5. Flutter: source interface, live/mock, provider, models
- [x] 5.1 `data/dashboard_source.dart`: `abstract interface class DashboardSource`;
      `DashboardLiveSource` (REST seed from `GET /api/v1/dashboard`, live via existing `/ws/market` +
      `/ws/portfolio`) + `DashboardMockSource`
- [x] 5.2 `application/dashboard_providers.dart`: Riverpod provider picking by
      `AppConfig.current.useMock` (mirror `backtestSourceProvider` shape); added
      `watchlistProvider`/`watchlistRepositoryProvider` on the same pattern
- [x] 5.3 Domain models with tolerant `fromJson` (money-as-string), each section carrying
      `available`/`asOf`; index model carries `prevClose` for client-side change recompute

## 6. Flutter: dashboard sections/widgets + watchlist + change-math fix
- [x] 6.1 Index cards (NIFTY/BANKNIFTY/SENSEX) with a client-tracked rolling-window sparkline
      (`fl_chart`, mirrors `pnl_chart.dart`) + change computed from `prevClose` vs latest tick
      (replaced the old running-sum approximation)
- [x] 6.2 Global-indices strip (Dow/Nasdaq/S&P/Nikkei/Hang Seng/FTSE)
- [x] 6.3 Commodities strip (MCX gold/crude/natgas/silver, INR) — ticks live via `security_id`
      threaded through from settings
- [x] 6.4 India VIX gauge — ticks live via `security_id`
- [x] 6.5 Portfolio snapshot tiles (positions, live P&L, today's realized P&L, margin) reusing
      `StatCard`/`PnlText`/`formatInr`
- [x] 6.6 Strategy-status chips (`GET /api/v1/strategies` via the composed dashboard endpoint)
- [x] 6.7 FII/DII panel (yesterday + 7-day), hidden when `available:false`
- [x] 6.8 Sentiment gauge (blend + sub-scores) + news list
- [x] 6.9 Next-expiry chips per index
- [x] 6.10 Editable watchlist (shared_preferences-backed add/remove) with live quote resolution:
      each watchlist symbol is matched against `data.indices`/`data.commodities` (the same
      index/LTP data path used elsewhere on the dashboard) and its quote renders inline when
      resolvable; symbols outside that path (e.g. arbitrary equities) render plain — never
      fabricated. A generic symbol-search/resolve backend endpoint for arbitrary instruments
      remains out of scope, noted alongside the backend-watchlist-sync open question.
- [x] 6.11 Each section respects its own `available` flag (hide/grey — never fabricate)

## 7. Flutter tests
- [x] 7.1 `app/test/dashboard_screen_test.dart`: overrides `dashboardSourceProvider` with a fixed
      `DashboardSource` (mirrors `MockDashboardSource` shape) + `watchlistRepositoryProvider` with
      `InMemoryWatchlistRepository`; covers change-vs-prev-close math, unavailable-section hiding
      (index card, FII/DII panel, sentiment/news), watchlist add/remove persistence, and watchlist
      live-quote resolution (shown for a priced symbol, plain for one outside the data path).
      8/8 passing.

## 8. Final verification
- [x] 8.1 `cd backend && task test` — 3 failures, all pre-existing/environment-dependent (confirmed
      via a stash-based A/B diff against the unmodified baseline, same failures either way; caused
      by real Dhan credentials in the local `.env` triggering live-mode wiring during tests, unrelated
      to this change). Zero regressions introduced. Re-verified after the `/opsx:verify` fix-up pass
      (watchlist quotes, PCR wiring, route de-duplication into `pdp/intel/sections.py`):
      `tests/intel/` (17 tests, incl. 3 new PCR-wiring poller tests) + `tests/options/test_routes.py`
      green except the same 3 pre-existing failures.
- [x] 8.2 `cd app && flutter analyze && flutter test` — 0 issues, 17/17 tests green (8 dashboard tests
      + 9 pre-existing backtest-console/detail tests)
- [ ] 8.3 Manual: `task dev` + `task app:run` — dashboard populates from `/api/v1/dashboard`, updates
      live over `/ws/market` + `/ws/portfolio`; `USE_MOCK=true` renders fully offline. **Not run in
      this session** — no live Dhan feed / device available; code path verified via automated tests
      and static analysis only. Recommend the owner do a manual pass before marking this change
      fully done.
- [x] 8.4 `openspec validate flutter-dashboard --strict` passes
