## Status: stub — backend returns hardcoded mock data; history is a random walk

Current state (as of 2026-06-30):
- Flutter UI scaffolded: `features/portfolio/presentation/advisory_tab.dart` — Holdings, Advice, History chart
- `GET /api/v1/portfolio/advisory` returns hardcoded sector allocation + 2 static advice items (`is_mock: true`)
- `GET /api/v1/portfolio/history` returns a random-walk 30-day P&L curve (`is_mock: true`)
- Advisory tab crash on empty history fixed (2026-06-30: guard added before `.reduce()`)

## Tasks

### 1. Backend — real holdings & advice
- [x] 1.1 Define holdings data source (Dhan holdings API or PostgreSQL positions table)
- [x] 1.2 Implement `GET /portfolio/advisory` from real holdings: compute sector breakdown, concentration
- [x] 1.3 Implement allocation advice rules (concentration > 40% → warn, cash drag → suggest deploy)
- [x] 1.4 Persist advice snapshots to MongoDB for audit trail

### 2. Backend — real P&L history
- [x] 2.1 Read `paper_journal` MongoDB collection for per-day realized P&L
- [x] 2.2 Aggregate 30-day cumulative P&L series
- [x] 2.3 Replace random-walk endpoint with real data; remove `is_mock` flag

### 3. Flutter advisory UI
- [x] 3.1 Handle `is_mock: true` flag — show banner "Demo data" when mock
- [x] 3.2 Use real sector allocation from API
- [x] 3.3 Advice action buttons: wire to order entry or screener deeplink

**Blocked by:** 1.1 (holdings source decision) and 2.1 (journal data confirmed complete first)

### 4. Repurpose screen as dedicated Holdings page (2026-07-03 follow-up)

The Portfolio screen's "Live Tracker" tab showed paper-trading F&O strategy
positions (`Position` table) — confusing since the user's actual demat
holdings (stocks/ETFs, `BrokerHolding`) never appeared there. F&O positions
already have a dedicated home on the Risk & Positions screen
(`risk_positions_screen.dart`), so this screen is repurposed to be the single
home for real holdings + insights.

- [x] 4.1 Backend: `GET /portfolio/holdings` — per-instrument detail (symbol,
      qty, avg cost, LTP, current value, P&L, P&L%, sector) + summary totals
      from `BrokerHolding`
- [x] 4.2 Flutter: rename screen/nav label "Portfolio" → "Holdings"
- [x] 4.3 Flutter: replace F&O "Live Tracker" tab with a real per-stock
      Holdings list + summary stat cards
- [x] 4.4 Flutter: keep sector allocation / advice / P&L history as the
      "Insights" tab
