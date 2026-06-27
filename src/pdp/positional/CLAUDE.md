# positional/ — Swing & Positional Position Tracking

Multi-leg swing/positional trades (F&O and equity). Distinct from intraday strategy positions.

## Files

| File | Purpose |
|------|---------|
| `models.py` | `PositionalGroup`, `PositionalLeg` Pydantic models |
| `routes.py` | FastAPI router (`/api/v1/positional`) |

## Key concepts

- **PositionalGroup** — a named trade (e.g. "NIFTY Jun strangle") with multiple legs
- **PositionalLeg** — a single option or equity position within a group, enriched with live Greeks
- Greeks enrichment: legs with `underlying + strike + option_type` get Greeks from the `/options/chain` API (or live WS Greeks)

## Note

This module tracks **manually entered** positional trades. Intraday strategy positions are tracked by `portfolio/` and `orders/`.
