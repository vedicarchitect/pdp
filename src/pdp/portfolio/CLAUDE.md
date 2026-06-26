# Portfolio Module

## Files

| File | Size | Role |
|------|------|------|
| `service.py` | 16.7 KB | `PortfolioService` — MTM P&L loop, fill aggregation, EOD snapshot, hard-cap callback |
| `hub.py` | 2 KB | `PortfolioHub` — WS fan-out for P&L updates |
| `routes.py` | 2 KB | REST: `/portfolio/summary`, `/portfolio/positions` |
| `ws.py` | 1.6 KB | `/ws/portfolio` WebSocket endpoint |
| `models.py` | 0.9 KB | `PortfolioSummary` response schema |

## Key Behaviour

- `PortfolioService` starts always (paper and live). Updates MTM every `PORTFOLIO_MTM_INTERVAL_SECONDS` (default 5s).
- Subscribes to fill events from `OrdersHub` — recalculates P&L on each fill.
- Hard-cap auto-kill: `set_hard_cap_callback(fn, RISK_DAILY_LOSS_CAP_INR)` → triggers `KillSwitchService` when daily loss exceeds cap.
- EOD snapshot controlled by `PORTFOLIO_EOD_SNAPSHOT=True` setting.
- LTP source: Redis key `ltp:<security_id>` (set by TickRouter, TTL 5s).
- **Position cache key**: `(strategy_id, security_id, exchange_segment, product)` — fixed 2026-06-18 (migration `0012`). Each strategy has its own position row; the portfolio sums across all strategies for total MTM.

## P&L Flow

```
Fill event (from OrdersHub)
  → PortfolioService._on_fill()
      → updates in-memory position map
      → recalculates realized + unrealized P&L
      → checks hard-cap threshold
      → PortfolioHub.broadcast(summary)  →  /ws/portfolio clients
```

## Settings

| Key | Default | Notes |
|-----|---------|-------|
| `PORTFOLIO_MTM_INTERVAL_SECONDS` | 5 | MTM loop interval |
| `PORTFOLIO_EOD_SNAPSHOT` | True | Save daily snapshot to MongoDB |
| `RISK_DAILY_LOSS_CAP_INR` | 50000 | Hard-cap for auto kill-switch |
| `RISK_PER_STRATEGY_LOSS_CAP_INR` | 20000 | Per-strategy soft cap |
| `RISK_SOFT_CAP_PCT` | 80.0 | % of cap that triggers warning |
