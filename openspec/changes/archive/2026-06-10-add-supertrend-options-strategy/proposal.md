## Why

We want a first concrete, fully-paper intraday strategy that exercises the strategy host
end-to-end: a **SuperTrend(3,1)** trend-follower on the NIFTY index that **sells options**
in the direction of the trend, scales in as the move continues, and is flat by EOD. This
also surfaces two missing platform pieces — a **live indicator engine** (only backtest had
indicators) and a **paper-trade journal** for daily P&L / progress review.

## What Changes

- New universal **SuperTrend** indicator computed once by the market engine on each closed
  bar and exposed to strategies (rule: indicators computed once, consumed by all).
- Strategy host gains read access to indicators and runtime feed subscribe/unsubscribe via
  the `StrategyContext`, so a strategy can pick and trade a dynamically-chosen option.
- New **`supertrend_short`** strategy: green → short OTM-1 PE, red → short OTM-1 CE of the
  nearest weekly expiry; flip closes + reverses; scale-in 2→5 lots while the trend holds;
  no entries before 09:30 IST; flatten all at 15:10 IST. Paper-only.
- New **paper-trade journal**: records every fill, computes per-day realized P&L (net of
  charges) and progress stats; exposed via REST and the frontend.

## Capabilities

### New Capabilities

- `supertrend-strategy`: SuperTrend(3,1) intraday option-selling paper strategy.
- `paper-journal`: per-day trade ledger + P&L/progress stats over paper fills.

### Modified Capabilities

- `market-data`: adds the universal SuperTrend indicator on closed bars.
- `strategy-host`: `StrategyContext` exposes indicator reads and feed subscribe/unsubscribe.

## Impact

Depends on `market-data`, `strategy-host`, `orders` (paper engine), `instruments`.
Paper-first: never routes live (orders go to the paper engine unless `LIVE=1` + broker wired).
