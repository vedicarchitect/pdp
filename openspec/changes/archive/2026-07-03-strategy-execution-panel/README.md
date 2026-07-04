# strategy-execution-panel

**Goal:** seamless directional-strangle execution + realtime monitoring, plus a persisted ML-expandable
pivot/levels warehouse.

**Minimal context set** (load only these when working this chunk):
- Backend monitor + strangle: `backend/pdp/strategy/routes.py`, `backend/pdp/strategies/directional_strangle.py`
- Poller default-on: `backend/pdp/main.py` (~L343), `backend/pdp/settings.py`, `backend/pdp/options/`
- Weekly bars: `backend/pdp/market/bars.py`, `backend/pdp/indicators/engine.py` + `warmup.py` + `pivots.py`
- Levels warehouse: `backend/pdp/indicators/levels_store.py` (new), `backend/scripts/backfill_levels.py` (new), `backend/pdp/options/gap_backfill.py` (reuse `trading_days/holidays`), `backend/scripts/backfill_spot.py` (template)
- Flutter: `app/lib/features/manage/` (new `tabs/strategy_execution_tab.dart`, `domain/`, `data/`, `application/`), `app/lib/core/network/`, `app/lib/core/theme/app_colors.dart`

See `proposal.md` → `design.md` → `tasks.md`. Spec deltas under `specs/`.

Full handoff notes also saved to user memory: `strategy_execution_panel_plan.md`.
