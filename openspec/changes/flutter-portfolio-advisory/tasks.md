## Status: stub — backend returns hardcoded mock data; history is a random walk

Current state (as of 2026-06-30):
- Flutter UI scaffolded: `features/portfolio/presentation/advisory_tab.dart` — Holdings, Advice, History chart
- `GET /api/v1/portfolio/advisory` returns hardcoded sector allocation + 2 static advice items (`is_mock: true`)
- `GET /api/v1/portfolio/history` returns a random-walk 30-day P&L curve (`is_mock: true`)
- Advisory tab crash on empty history fixed (2026-06-30: guard added before `.reduce()`)

## Tasks

### 1. Backend — real holdings & advice
- [ ] 1.1 Define holdings data source (Dhan holdings API or PostgreSQL positions table)
- [ ] 1.2 Implement `GET /portfolio/advisory` from real holdings: compute sector breakdown, concentration
- [ ] 1.3 Implement allocation advice rules (concentration > 40% → warn, cash drag → suggest deploy)
- [ ] 1.4 Persist advice snapshots to MongoDB for audit trail

### 2. Backend — real P&L history
- [ ] 2.1 Read `paper_journal` MongoDB collection for per-day realized P&L
- [ ] 2.2 Aggregate 30-day cumulative P&L series
- [ ] 2.3 Replace random-walk endpoint with real data; remove `is_mock` flag

### 3. Flutter advisory UI
- [ ] 3.1 Handle `is_mock: true` flag — show banner "Demo data" when mock
- [ ] 3.2 Use real sector allocation from API
- [ ] 3.3 Advice action buttons: wire to order entry or screener deeplink

**Blocked by:** 1.1 (holdings source decision) and 2.1 (journal data confirmed complete first)
