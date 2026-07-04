## Why

To be "flexible enough to add a new strategy + params and use it," and to make paper reproduce a
backtest, both sides must run the *same* config under the *same* identity. Today they don't: live
configs (`pdp/strategy/registry.py`) require a top-level `id` like `directional_strangle_nifty`,
while backtest configs (`strangle_config.py`, `strategy_config.py`, `backtest/configs/*.yaml`) have
no `id` at all and three incompatible schemas, and a backtest run's `strategy_id` is only a coarse
family label (`strangle`) parsed from the run id — which matches no live id. The console's launch
flow still uses a raw-JSON textbox. This change adds one registry, keyed like live strategies, that
both the backtest and live/paper paths resolve against, and a `/strategies` API with an editable
param schema so a new strategy/params can be registered and immediately backtested.

## What Changes

- **Unified strategy registry**: a registry keyed by canonical strategy id (as live strategies are)
  that enumerates available strategies across the live `strategies/*.yaml` and the backtest configs,
  reconciling their schemas behind one interface (id, engine/kind, editable params + defaults +
  bounds, underlying/index).
- **`GET /api/v1/strategies`**: lists registered strategies with their editable param schema so the
  console picker replaces the raw-JSON textbox and a new strategy/params can be added and run.
- **Canonical run identity**: map each backtest run's coarse family label to a canonical strategy id
  so runs, paper trades, and comparisons key on the same id (feeds change 3's vs-paper and change 1's
  decision trace).

## Capabilities

### New Capabilities
- `strategy-registry`: a single, canonical-id-keyed registry spanning live and backtest strategy
  configs, plus a `/strategies` API exposing each strategy's editable param schema and defaults.

### Modified Capabilities
- (none — the registry reads the existing live registry and backtest configs; it does not change
  their requirements. Backtest configs MAY carry an explicit canonical `strategy_id`, defaulting to a
  filename-derived id, without altering `backtest-config-yaml` behavior.)

## Impact

- Backend: a new registry module reconciling `pdp/strategy/registry.py` (`StrategyConfig`) with the
  backtest config dataclasses (`pdp/backtest/{strangle_config,strategy_config}.py`) and
  `backtest/configs/*.yaml`; a `GET /api/v1/strategies` route; a canonical-id mapping used by the run
  warehouse (change 1) and the paper comparison (change 3).
- Enables the change-5 launch flow (strategy picker + editable params) and clean `strategy_id` keys
  for parity.
- New skill: `/strategy:add`.
