# alerts/ — Alert Engine

Price/Greeks rule evaluation + WebSocket delivery.

## Files

| File | Purpose |
|------|---------|
| `models.py` | `AlertRecord` ORM model (PG) |
| `schemas.py` | Pydantic request/response schemas |
| `enums.py` | `AlertCondition`, `AlertChannel`, `AlertStatus` enums |
| `evaluator.py` | `AlertEvaluator` — evaluates rules against live ticks/Greeks |
| `service.py` | `AlertService` — CRUD, rule persistence |
| `channels.py` | Alert delivery channels (WS, future: webhook) |
| `ws.py` | `AlertsHub` — WebSocket fan-out for alert events |
| `routes.py` | FastAPI router (`/api/v1/alerts`) |

## Key types

- Alerts persist in PostgreSQL `alerts` table
- Evaluated on each TickRouter tick (price, Greeks) and each bar close (indicator-based)
- Triggered alerts pushed to `AlertsHub` WebSocket subscribers (`ws://localhost:8000/ws/alerts`)
- Alert lifecycle: `ARMED` → `TRIGGERED` → `RESOLVED` (auto-resolves when condition clears)

## Currently implemented condition types (`AlertCondition` enum)

| Condition | Triggers when |
|---|---|
| `PRICE_GT` | tick price > threshold |
| `PRICE_LT` | tick price < threshold |
| `DELTA_GT` | option delta > threshold |
| `DELTA_LT` | option delta < threshold |
| `GAMMA_GT` | option gamma > threshold |
| `GAMMA_LT` | option gamma < threshold |
| `VEGA_GT` | option vega > threshold |
| `VEGA_LT` | option vega < threshold |
| `PNL_GT` | position P&L > threshold |
| `PNL_LT` | position P&L < threshold |

## Planned condition types (not yet implemented — need OpenSpec changes)

These are required by the platform's monitoring roadmap (see RUNBOOK §16):

| Condition | Event | Infrastructure needed |
|---|---|---|
| `EMA_CROSS_ABOVE` | EMA fast crosses above EMA slow | `IndicatorEngine.get_ema()` — already computed |
| `EMA_CROSS_BELOW` | EMA fast crosses below EMA slow | same |
| `SUPERTREND_FLIP` | SuperTrend direction changes on any TF | `IndicatorEngine.get()` — already computed |
| `PRICE_NEAR_LEVEL` | Price within tolerance of FVG/Fib/EMA level | FVG, FibLevels, EMA all in suite |
| `SESSION_BREAK` | Price breaks PDH/PDL/PWH/PWL/PMH/PML | `PivotTracker` — prior-session HLC available |
| `GAP_UP` / `GAP_DOWN` | First bar open vs prior-session close | `PivotTracker` — prior close available |
| `VOLUME_SPIKE` | Bar volume > N × rolling-average volume | `VWMATracker` — rolling volume available |
| `OI_WALL_NEAR` | Price within N points of OI wall strike | Options analytics — `oi_wall_above/below` |
| `OI_TREND_CHANGE` | PCR crosses threshold or OI accumulation flip | Options analytics — PCR available |
| `NET_DELTA_GT/LT` | Portfolio net delta exceeds signed threshold | Position Greeks — already in DB |
| `TRADE_COUNT_GT` | More than N trades placed today | Journal stats — already computed |
| `PREMIUM_RECEIVED_GT` | Cumulative premium collected > ₹X | Journal stats — already computed |

## Evaluator extension pattern

To add a new condition:

1. Add the condition name to `AlertCondition` in `enums.py`.
2. Add the evaluation method in `AlertEvaluator` (e.g. `evaluate_ema_cross()`).
3. Call it from the appropriate hook — `TickRouter.on_bar()` for bar-close conditions,
   `TickRouter._route_tick()` for tick conditions.
4. Write a migration if the new condition stores extra metadata (currently not needed —
   `threshold` covers most numeric conditions; add a `metadata JSON` column for multi-param
   conditions like `EMA_CROSS_ABOVE` which need `fast_period` + `slow_period`).

## Adding Telegram delivery

`AlertChannel.TELEGRAM` is defined but not yet wired. To enable:
1. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `settings.py`.
2. Implement `channels.py:send_telegram(notification)`.
3. Call it from `AlertEvaluator._fire_notification()` when `alert.channel == "TELEGRAM"`.
