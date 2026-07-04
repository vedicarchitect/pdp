## 1. Registry facade

- [x] 1.1 Add a registry module exposing `StrategyEntry {id, kind, underlying, params_schema, defaults}`, adapting the live loader (`pdp/strategy/registry.py:load_all`) and the backtest config dataclasses (`strangle_config.py`/`strategy_config.py` `to_dict()` + `backtest/configs/*.yaml`).
- [x] 1.2 Canonical id: read an optional `strategy_id` key from backtest configs; otherwise derive a stable id from the filename. Live configs use their existing `id`.

## 2. Param schema

- [x] 2.1 Introspect the editable param schema (name, type, default) from each config type.
- [x] 2.2 Add a curated bounds table for knobs with sensible ranges (e.g. `take_profit_pct ∈ (0,1]`, `timeframe_min ∈ {3,5,15,30,60}`).

## 3. API

- [x] 3.1 Add `GET /api/v1/strategies` returning each strategy's canonical id, kind, underlying, and editable param schema + defaults.

## 4. Canonical run identity

- [x] 4.1 Expose `canonical_id(run_label, underlying)` and wire it into change 1's run identity (`store.py`) and change 3's vs-paper resolver.

## 5. Add-a-strategy

- [x] 5.1 Support registering a new strategy (canonical id + kind + params) so it appears in `GET /api/v1/strategies` and is selectable as a backtest launch target; persist as a `backtest/configs/*.yaml` record.

## 6. Skill

- [x] 6.1 `.claude/skills/strategy-add/SKILL.md` (`/strategy:add`) — register a new strategy + params via the registry, validate against the param schema, optionally launch a first backtest via `/backtest:run`.

## 7. Tests + spec sync

- [x] 7.1 Unit tests: registry enumerates live + backtest entries; filename-derived vs explicit id; param-schema introspection + bounds; `canonical_id` label→id mapping.
- [x] 7.2 `task test` / `task lint` / `task typecheck` clean for touched modules; `openspec validate strategy-registry-unification --strict` passes.
