## Why

(STUB.) The backend hot path ships first; the React shell follows in its own change with routes, hooks, and a real-time WebSocket layer.

## What Changes

- Vite + React 19 + TypeScript + TanStack Router + TanStack Query + shadcn/ui + Tailwind 4 scaffold under `frontend/`.
- Routes: `/intraday`, `/positional`, `/portfolio`, `/strategies`, `/backtest`, `/instruments`.
- Hooks: `useMarketWS`, `useLTP`, `usePnL`, `useOrderStream`.
- Charting via `lightweight-charts`.
- Global `PAPER` / `LIVE` mode banner driven by `X-Trade-Mode` response header.

## Capabilities

### New Capabilities

- `frontend-shell`: React SPA shell with routing, query layer, WebSocket hooks, charting.

### Modified Capabilities

(none)

## Impact

Independent track — backend changes do not block frontend scaffold start, but real wiring waits on `market-data` and `order-execution`.
