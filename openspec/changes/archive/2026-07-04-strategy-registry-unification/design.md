## Context

Two worlds don't line up (confirmed by exploration):
- Live: `pdp/strategy/registry.py` `StrategyConfig` (pydantic) with required `id` (`load_one`
  enforces id==filename), `class`, `watchlist`, `params`, `risk`. Live ids:
  `directional_strangle_{nifty,banknifty,sensex}`.
- Backtest: `strangle_config.py` `StrangleConfig` (dataclass, has `underlying`+`security_id`, nested
  `weights`, `ratio_table`) and `strategy_config.py` `StrategyConfig` (dataclass, ST knobs, no
  underlying/id), plus a third legacy options YAML dialect. None have an `id` or `class`.
- A backtest run's `strategy_id` is a coarse label parsed from the run id (`store.py`, e.g.
  `strangle`), which matches no live id.

Change 1 (decision trace / run identity) and change 3 (vs-paper) both need a clean `strategy_id`;
change 5's launch flow needs an editable param schema.

## Goals / Non-Goals

**Goals:**
- One registry keyed by canonical id spanning live + backtest configs.
- `GET /api/v1/strategies` with an editable param schema (names/types/defaults/bounds).
- Register-a-new-strategy → immediately backtestable, no code change.
- A canonical run-identity mapping used by changes 1 and 3.

**Non-Goals:**
- Rewriting the backtest config dataclasses into one class — we reconcile behind an interface, not by
  forcing a single schema.
- The Flutter picker UI (change 5 consumes `/strategies`).
- Changing live strategy loading/execution.

## Decisions

### 1. A thin registry facade over existing loaders, not a rewrite
Introduce a registry that adapts each source into a common `StrategyEntry {id, kind, underlying,
params_schema, defaults}`: live via `registry.load_all`, backtest via the config dataclasses'
`to_dict()` (StrangleConfig/StrategyConfig). Rationale: avoids a risky big-bang schema merge; each
engine keeps its own config type. Alternative rejected: one unified config dataclass (too invasive,
breaks the two proven engines).

### 2. Canonical id: explicit key or filename-derived
Backtest configs MAY add an optional `strategy_id` key; when absent, derive a stable id from the
filename (e.g. `strangle_nifty_hedged` → `strangle_nifty_hedged`, or map to the matching live id via
underlying). Live configs already have `id`. Rationale: no forced edit to 15 YAMLs; explicit override
available when a backtest config should map onto a live id for parity.

### 3. Param schema is introspected from the config type
Derive the editable param schema from the dataclass/pydantic fields (name, type, default) plus a
small curated bounds table for the knobs that have sensible ranges (e.g. `take_profit_pct ∈ (0,1]`,
`timeframe_min ∈ {3,5,15,30,60}`). Rationale: schema stays in sync with the config definition; bounds
are additive metadata.

### 4. Run-identity mapping lives in the registry
The registry exposes `canonical_id(run_label, underlying)` used by `store.py` (change 1) and the
vs-paper resolver (change 3). Rationale: one place owns the label→id mapping, so warehouse and
comparison agree.

## Risks / Trade-offs

- [Backtest vs live param name/nesting mismatches (e.g. flat `w_ema_1h` vs nested `weights`)] → the
  adapter normalizes to a flat editable schema; a per-engine (de)serializer maps back to the engine's
  native shape on launch.
- [Ambiguous label→id mapping when multiple configs share an underlying] → require an explicit
  `strategy_id` on the config to disambiguate; otherwise pick the promoted/default and warn.
- [Schema drift if a config field changes] → schema is introspected, not hand-maintained, so it
  follows the config definition automatically.

## Migration Plan

1. Add the registry facade + `StrategyEntry` adapters over live + backtest loaders.
2. Add the curated bounds table + param-schema introspection.
3. Add `GET /api/v1/strategies`.
4. Expose `canonical_id(...)` and wire it into change 1's run identity and change 3's resolver.
5. Author `/strategy:add`.
Rollback: the registry + API are additive reads; nothing changes existing config loading or execution.

## Open Questions

- Should a newly registered strategy persist (written as a `backtest/configs/*.yaml` / `strategies/*.yaml`)
  or live only in the registry until promoted? Leaning: write a backtest config YAML on add (so it's a
  reproducible record), promote to a live `strategies/*.yaml` only via the existing PASS-gated flow.
