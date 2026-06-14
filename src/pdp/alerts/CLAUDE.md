# alerts/ — Alert Engine

Price/Greeks rule evaluation + WebSocket delivery.

## Files

| File | Purpose |
|------|---------|
| `models.py` | `Alert` ORM model (PG) |
| `schemas.py` | Pydantic request/response schemas |
| `enums.py` | `AlertType`, `AlertStatus` enums |
| `evaluator.py` | `AlertEvaluator` — evaluates rules against live ticks/Greeks |
| `service.py` | `AlertService` — CRUD, rule persistence |
| `channels.py` | Alert delivery channels (WS, future: webhook) |
| `ws.py` | `AlertsHub` — WebSocket fan-out for alert events |
| `routes.py` | FastAPI router (`/api/v1/alerts`) |
| `tests.py` | Inline evaluation tests |

## Key types

- Alerts persist in PostgreSQL `alerts` table
- Evaluated on each TickRouter tick and each option chain refresh
- Triggered alerts pushed to `AlertsHub` WebSocket subscribers
