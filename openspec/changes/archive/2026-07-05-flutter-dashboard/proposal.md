## Why

The app has only the portfolio slice; there is no home dashboard. The new canonical screen shows
live indices, global markets, commodities, VIX, FII/DII flow, sentiment/news, portfolio snapshot,
watchlist, and expiry — every value real or honestly marked unavailable, never fabricated.

## What Changes

A blazing-fast dashboard: index cards (NIFTY/BANKNIFTY/SENSEX, vs-prev-close change math),
global-market strip (Dow/Nasdaq/S&P/Nikkei/Hang Seng/FTSE via `yfinance`), MCX commodities strip
(gold/crude/natgas/silver in INR via the existing Dhan feed), India VIX gauge, FII/DII panel
(yesterday + 7-day, via `nsepython`), a blended sentiment gauge (news headlines via `feedparser`/
`vaderSentiment` + market internals) with its news feed, next-expiry chips, portfolio snapshot +
live P&L, today's realized P&L, margin, strategy-status chips, and a locally-persisted editable
watchlist. Third-party data runs off the hot path via a background poller + cache; every section
degrades honestly to `available:false` rather than showing a placeholder. GIFT NIFTY is omitted for
v1 (no reliable free source).

## Capabilities

### New Capabilities
- `flutter-dashboard`: house-convention Flutter dashboard screen — see `specs/flutter-dashboard/spec.md`.
- `dashboard-market-feeds`: backend global-indices/commodities/VIX/next-expiry/news/sentiment feeds
  + composed `/api/v1/dashboard` — see `specs/dashboard-market-feeds/spec.md`.

### Modified Capabilities
- `fii-dii-data`: real `NseFIIDIISource` (nsepython) + 7-day history, replacing the always-null stub
  as default when `INTEL_ENABLED` — see `specs/fii-dii-data/spec.md`.
