## Status: stub — backend engine not yet built

Current state (as of 2026-06-30):
- Flutter UI scaffolded: `features/screener/` with `ScreenerScreen` + Execute button
- Backend `GET /api/v1/screener/run` returns empty `{"results": [], "note": "..."}` (safe no-op)
- No real screener engine exists

## Tasks

### 1. Backend screener engine
- [ ] 1.1 Design signal engine (EMA alignment, 9EMA×20MA/daily, volume surge, 50MA proximity)
- [ ] 1.2 Read OHLCV bars from MongoDB warehouse for screener universe
- [ ] 1.3 Implement `ScreenerEngine` class — per-symbol signal evaluation, result ranking
- [ ] 1.4 Wire `GET /api/v1/screener/run?strategy=<name>` to real engine output
- [ ] 1.5 Add watchlist persistence (PostgreSQL or Redis)

### 2. Flutter screener UI
- [ ] 2.1 Display real results from API (symbol, LTP, signal criteria, volume)
- [ ] 2.2 Prebuilt strategy selector (EMA, MA, volume, proximity)
- [ ] 2.3 Remove `(Mock)` SnackBar from Execute button; wire to real order placement
- [ ] 2.4 Add watchlist add/remove

**Blocked by:** 1.1 (design session needed before implementation)
