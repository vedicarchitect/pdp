---
name: strategy:add
description: Register a new strategy + params via the unified strategy registry, validate against its param schema, and optionally launch a first backtest. Use when the user wants to add a new strategy/param variant without editing source, then try it out.
metadata:
  author: pdp
  version: "1.0"
---

Register a new backtest strategy config through the unified strategy registry
(`strategy-registry-unification`) so it immediately shows up in `GET /api/v1/strategies` and is
launchable — no code change, no restart.

## Input

Ask for whatever is missing rather than guessing:
- `strategy_id` — a canonical id, unique across both live and backtest registrations (check
  `GET /api/v1/strategies` first if unsure)
- `kind` — `strangle` (directional-strangle engine) or `supertrend` (SuperTrend option-selling
  engine)
- `params` — a dict of engine knobs. Only the fields the user wants to override from the
  engine's defaults are required; unset fields fall back to the dataclass default
  (`StrangleConfig` / `pdp.backtest.strategy_config.StrategyConfig`). For `strangle`, include
  `underlying` (NIFTY/BANKNIFTY/SENSEX) if it's not NIFTY.
- Whether to immediately run a backtest against it (and the date window if so)

## Steps

1. **Check the param schema first** so edits land on real knobs, not typos:

   ```
   curl -s http://localhost:8000/api/v1/strategies | jq '.strategies[] | select(.kind=="<kind>") | .params_schema' | head -50
   ```

   Use an existing same-`kind` entry's `params_schema`/`defaults` as the template — bounds
   (`min`/`max`/`enum`) are advisory metadata for the client; the backend's own
   `validate()` is the actual gate.

2. **Register via the API**:

   ```
   curl -s -X POST http://localhost:8000/api/v1/strategies/register \
     -H "Content-Type: application/json" \
     -d '{"strategy_id": "<id>", "kind": "<strangle|supertrend>", "params": {...}}'
   ```

   - `201` → registered; response includes the resolved `defaults` (full config, ready to use
     as a `POST /runs` body) and `params_schema`.
   - `409` → a config file already exists at that id — pick a different `strategy_id`.
   - `422` → either an unknown `kind`, or the engine's own `validate()` rejected a param value
     (message says which field and why) — report the exact message back to the user and ask
     for a corrected value; don't guess a fix.

3. **If the API isn't running**, fall back to calling the registry directly:

   ```
   cd backend && uv run python -c "
   from pdp.strategy.unified_registry import register_strategy
   entry = register_strategy('<id>', '<kind>', {...})
   print(entry.id, entry.defaults)
   "
   ```

   This writes `backend/backtest/configs/<strategy_id>.yaml` — commit it, since configs are
   the reproducible "what we ran" record (see `backend/backtest/CLAUDE.md`).

4. **Confirm it's live** in the registry:

   ```
   curl -s http://localhost:8000/api/v1/strategies | jq '.strategies[] | select(.id=="<id>")'
   ```

5. **Offer to backtest it immediately**: if the user wants a first run, hand the registered
   `defaults` dict straight to `/backtest:run` as the inline config (no need to re-derive a
   config file path — the registry entry *is* the config).

## Notes

- Registration is additive only — it never edits an existing config file or the live
  `strategies/*.yaml` configs. Promoting a validated backtest config to a *live* paper strategy
  still goes through the existing PASS-gated `/backtest:promote` flow, not this skill.
- `kind` is currently limited to the two engines the registry adapts (`strangle`,
  `supertrend`); the legacy `options-strategy` YAML dialect isn't unified yet.
