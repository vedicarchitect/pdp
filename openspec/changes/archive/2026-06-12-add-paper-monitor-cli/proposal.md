## Why

`monitor.pl` is the read-only terminal client the user actually watches during a paper session.
It is undocumented (no capability spec) and carries a **hard-coded weekly expiry**
(`$CHAIN_EXPIRY = '2026-06-09'`) plus hard-coded `Jun9` instrument labels. After expiry rolled to
2026-06-16 the monitor requests a stale chain and mislabels every leg — so the live blotter no
longer reflects what the strategy is trading, which is exactly the "monitor.pl has a discrepancy"
symptom. The monitor also has no way to show the new per-leg / daily-loss stops, so a reader can't
see why a leg closed. Capturing this as a capability lets us fix it spec-first.

## What Changes

- Establish a `paper-monitor-cli` capability describing `monitor.pl`: a zero-side-effect client
  that polls Redis + the FastAPI read endpoints once per second and renders per-strategy blotters.
- **Derive the nearest weekly expiry dynamically** (next Tuesday, NIFTY weekly) instead of the
  hard-coded constant, and label instruments from the resolved expiry rather than a literal `Jun9`.
- Surface **risk-stop context**: show the configured per-leg stop and daily loss cap and flag
  when a leg's MTM is approaching its stop, so a stop-driven close is explainable on screen.
- Keep the monitor strictly read-only (no order mutation), consistent with its current design.

## Capabilities

### New Capabilities

- `paper-monitor-cli`: read-only terminal monitor for the paper SuperTrend session.

## Impact

- Touches `monitor.pl` only; no Python/runtime changes.
- Depends on existing read endpoints (`/api/v1/portfolio/*`, `/api/v1/orders`, `/api/v1/trades`,
  `/api/v1/options/NIFTY/chain`, `/api/v1/strategies`) and Redis (`ltp:*`, `st:*`).
- Pairs with `add-strategy-risk-controls`: once the strategy enforces stops, the monitor can
  display them.
