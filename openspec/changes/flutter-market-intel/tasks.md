## Status: stub — all backend feeds are hardcoded static data

Current state (as of 2026-06-30):
- Flutter UI scaffolded: `features/intel/` with news, sentiment, commodities, calendar tabs
- All 4 backend endpoints (`/intel/news`, `/intel/sentiment`, `/intel/commodities`, `/intel/calendar`) return static hardcoded data
- No real external data feeds wired

## Tasks

### 1. Backend external data feeds
- [ ] 1.1 News: integrate RSS/API feed (e.g. NSE announcements, moneycontrol headlines)
- [ ] 1.2 Sentiment: define data source (X API, Reddit, internal signal)
- [ ] 1.3 Commodities: wire live prices (Gold/Silver via MCX feed or public API)
- [ ] 1.4 Economic calendar: source (Investing.com API or manual CSV import)
- [ ] 1.5 Cache feeds in Redis with appropriate TTLs

### 2. Flutter intel UI
- [ ] 2.1 Display real news with timestamps, source attribution, link-out
- [ ] 2.2 Sentiment gauge driven by real score
- [ ] 2.3 Commodity prices with change indicators
- [ ] 2.4 Calendar with upcoming high-impact events highlighted

**Blocked by:** 1.1–1.4 (external data source decisions needed in design session)
