# ML Package (`src/pdp/ml/`)

Classical gradient-boosted-tree signals trained offline and served read-only online.

## Files

| File | Role |
|------|------|
| `registry.py` | Feature schema, label schema, artifact path/version contract, drift guard (`SchemaDriftError`) |
| `features.py` | **Single** leakage-safe feature builder — used identically offline (training) and online (inference). Input: closed bar + indicator `Snapshot` + `SuperTrendState`. |
| `labels.py` | `directional_labels()` (forward-return buckets: up/flat/down) and `expiry_labels()` (expiry-close-zone buckets). Labels computed only during training. |
| `train.py` | Offline trainer: load `market_bars` → build features+labels → purged/embargoed walk-forward CV → fit LightGBM → write versioned artifact + report. |
| `infer.py` | Load artifact once → produce `MLSignalState` (class probs + argmax + version); schema-drift → no signal. |

## Artifact layout

```
data/models/<version>/
    model.lgb        # LightGBM binary
    meta.json        # ArtifactMeta (feature/label schema, training window, head type)
    report.json      # CV scores + feature importances
```

## Settings (all via `get_settings()`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `ML_ENABLED` | `False` | Master switch |
| `ML_MODEL_DIR` | `data/models` | Artifact root |
| `ML_ACTIVE_VERSION` | `""` | Which artifact to serve; empty = no model |
| `ML_HORIZON` | `5` | Bars ahead for directional label |
| `ML_UP_THRESHOLD` | `0.002` | Return fraction → "up" |
| `ML_DOWN_THRESHOLD` | `-0.002` | Return fraction → "down" |
| `ML_EXPIRY_HEAD_ENABLED` | `False` | Phase-2 expiry-close head |

## Key constraints

- **No look-ahead**: `features.py` uses only closed-bar data (at or before bar close).
- **Single builder**: same code path in `train.py`, `infer.py`, and the backtest — guarantees live = backtest = offline.
- **Schema drift guard**: `registry.check_schema()` raises `SchemaDriftError` when artifact's feature list differs from the live builder's list — inference returns `None` rather than a silently wrong value.
- **Non-blocking**: inference runs after `on_bar` caching and reuses the already-computed snapshot; no blocking I/O on the hot path.
- **Opt-in**: `ML_ENABLED=False` (default) and `ML_ACTIVE_VERSION=""` mean nothing is loaded.

## Training

```bash
task ml:train                                     # default security/timeframe from settings
task ml:train -- --security-id 13 --timeframe 15m --days 90
```

## Adding a feature

1. Add the column name to `FEATURE_SCHEMA` in `registry.py`.
2. Compute it in `build_feature_row()` in `features.py`.
3. Bump the artifact version and retrain.

## Phase-2 expiry head

The expiry head consumes option-chain analytics features (`max_pain`, `pcr`, `gex`, `iv_atm`, `india_vix`, `oi_wall_above`, `oi_wall_below`, `max_pain_distance`).
It is gated behind `ML_EXPIRY_HEAD_ENABLED=True` and is disabled by default.
