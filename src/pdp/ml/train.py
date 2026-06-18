"""Offline trainer for the candlestick-ml-signals directional head.

Pipeline:
1. Load ``market_bars`` for a (security_id, timeframe) window from MongoDB.
2. Replay bars through the indicator suite to build per-bar Snapshots and
   SuperTrend states (same tracker classes as live — guarantees parity).
3. Build feature rows with ``ml.features.build_feature_rows``.
4. Compute forward-return labels with ``ml.labels.directional_labels``.
5. Drop rows where the label is None (end-of-series horizon gap).
6. Purged / embargoed walk-forward cross-validation.
7. Fit a final LightGBM model on the full training window.
8. Write versioned artifact (model + meta + report).

Run via:
    task ml:train
    task ml:train -- --security-id 13 --timeframe 15m --days 90
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()


def _load_bars(
    mongo_uri: str,
    db_name: str,
    security_id: str,
    timeframe: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict]:
    """Load market_bars from MongoDB for the given (sid, tf, window)."""
    from pymongo import MongoClient

    client: MongoClient = MongoClient(mongo_uri)
    col = client[db_name]["market_bars"]
    cursor = col.find(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": timeframe,
            "ts": {"$gte": from_dt, "$lte": to_dt},
        }
    ).sort("ts", 1)
    return list(cursor)


def _bars_to_bar_closed(raw_bars: list[dict]) -> list[Any]:
    """Convert MongoDB documents to BarClosed objects."""
    from decimal import Decimal

    from pdp.market.bars import BarClosed

    result = []
    for b in raw_bars:
        result.append(
            BarClosed(
                security_id=b["metadata"]["security_id"],
                timeframe=b["metadata"]["timeframe"],
                bar_time=b["ts"],
                open=Decimal(str(b.get("open", b.get("close", 0)))),
                high=Decimal(str(b["high"])),
                low=Decimal(str(b["low"])),
                close=Decimal(str(b["close"])),
                volume=int(b.get("volume", 0)),
                oi=int(b.get("oi", 0)),
            )
        )
    return result


def _build_snapshots(
    bars: list[Any],
    security_id: str,
    timeframe: str,
    indicator_config: list[dict],
) -> tuple[list[Any], list[Any]]:
    """Replay bars through the indicator engine; return (snapshots, supertrends)."""
    from pdp.indicators.engine import IndicatorEngine

    engine = IndicatorEngine(st_period=10, st_multiplier=2.0)
    engine.configure_suite(security_id, timeframe, indicator_config)
    snapshots = []
    supertrends = []
    for bar in bars:
        st = engine.on_bar(bar)
        snap = engine.get_snapshot(security_id, timeframe)
        snapshots.append(snap)
        supertrends.append(st)
    return snapshots, supertrends


def _purged_walk_forward_cv(
    feat_mat: list[list[float]],
    y: list[int],
    feature_names: list[str],
    label_schema: list[str],
    n_splits: int = 5,
    embargo: int = 10,
) -> list[dict]:
    """Purged walk-forward cross-validation with embargo.

    Each validation fold is separated from its training data by ``embargo`` rows
    so label-horizon leakage is prevented. Returns per-fold metric dicts.
    """
    import lightgbm as lgb
    import numpy as np

    n = len(feat_mat)
    fold_size = n // (n_splits + 1)
    results = []

    for k in range(n_splits):
        train_end = fold_size * (k + 1)
        val_start = train_end + embargo
        val_end = min(val_start + fold_size, n)
        if val_start >= n:
            break

        x_tr = np.array(feat_mat[:train_end], dtype=np.float32)
        y_tr = np.array(y[:train_end], dtype=np.int32)
        x_val = np.array(feat_mat[val_start:val_end], dtype=np.float32)
        y_val = np.array(y[val_start:val_end], dtype=np.int32)

        dtrain = lgb.Dataset(x_tr, label=y_tr, feature_name=feature_names, free_raw_data=False)
        dval = lgb.Dataset(x_val, label=y_val, feature_name=feature_names, free_raw_data=False)

        params = {
            "objective": "multiclass",
            "num_class": len(label_schema),
            "metric": "multi_logloss",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "verbosity": -1,
            "seed": 42,
        }
        model = lgb.train(
            params,
            dtrain,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(-1)],
        )

        preds = model.predict(x_val)
        pred_classes = np.argmax(preds, axis=1)
        acc = float(np.mean(pred_classes == y_val))
        results.append({"fold": k, "accuracy": acc, "n_train": len(x_tr), "n_val": len(x_val)})
        log.info("cv_fold_done", fold=k, accuracy=round(acc, 4), n_val=len(x_val))

    return results


def train(
    security_id: str,
    timeframe: str,
    days: int = 90,
    version: str | None = None,
    head: str = "directional",
    progress_cb: Any = None,
) -> str:
    """Train a LightGBM model and write a versioned artifact. Returns the version string."""
    import lightgbm as lgb
    import numpy as np

    from pdp.ml.features import build_feature_rows, feature_names
    from pdp.ml.labels import directional_labels
    from pdp.ml.registry import (
        LABEL_SCHEMA_DIRECTIONAL,
        ArtifactMeta,
        artifact_dir,
        artifact_model_path,
        artifact_report_path,
    )
    from pdp.settings import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    to_dt = now
    from_dt = now - timedelta(days=days)

    log.info("ml_train_start", security_id=security_id, timeframe=timeframe, days=days, head=head)

    # 1. Load bars
    if progress_cb:
        progress_cb(10, "Loading bars...")
    raw = _load_bars(settings.MONGO_URI, settings.MONGO_DB_NAME, security_id, timeframe, from_dt, to_dt)
    if len(raw) < 50:
        raise ValueError(f"Not enough bars for training: {len(raw)} (need ≥ 50)")

    bars = _bars_to_bar_closed(raw)
    log.info("ml_train_bars_loaded", n=len(bars))

    # 2. Build indicator snapshots (same config as live)
    indicator_config = [
        {"family": "ema", "periods": [9, 20, 50]},
        {"family": "rsi"},
        {"family": "vwap"},
        {"family": "macd"},
        {"family": "candlestick"},
        {"family": "elliott"},
        {"family": "fib_levels"},
        {"family": "elder_impulse"},
        {"family": "pivots"},
    ]
    snapshots, supertrends = _build_snapshots(bars, security_id, timeframe, indicator_config)

    if progress_cb:
        progress_cb(30, "Computing features...")
    # 3. Build feature rows
    feat_rows = build_feature_rows(bars, snapshots, supertrends)

    if progress_cb:
        progress_cb(50, "Computing labels...")
    # 4. Labels
    horizon = settings.ML_HORIZON
    label_names = LABEL_SCHEMA_DIRECTIONAL
    label_index = {name: i for i, name in enumerate(label_names)}
    raw_labels = directional_labels(
        bars,
        horizon=horizon,
        up_threshold=settings.ML_UP_THRESHOLD,
        down_threshold=settings.ML_DOWN_THRESHOLD,
    )

    # 5. Drop rows without a label
    feat_cols = feature_names()
    feat_mat: list[list[float]] = []
    y: list[int] = []
    for row, lbl in zip(feat_rows, raw_labels, strict=False):
        if lbl is None:
            continue
        feat_mat.append([row.get(col, 0.0) for col in feat_cols])
        y.append(label_index[lbl])

    log.info("ml_train_dataset", n_samples=len(feat_mat), n_features=len(feat_cols))
    if len(feat_mat) < 30:
        raise ValueError(f"Too few labeled samples after label horizon drop: {len(feat_mat)}")

    if progress_cb:
        progress_cb(60, "Running cross-validation...")
    # 6. CV
    cv_results = _purged_walk_forward_cv(feat_mat, y, feat_cols, label_names, embargo=horizon)

    if progress_cb:
        progress_cb(80, "Training final model...")
    # 7. Final model on full data
    x_arr = np.array(feat_mat, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)
    dtrain = lgb.Dataset(x_arr, label=y_arr, feature_name=feat_cols, free_raw_data=False)
    params = {
        "objective": "multiclass",
        "num_class": len(label_names),
        "metric": "multi_logloss",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "n_estimators": 300,
        "verbosity": -1,
        "seed": 42,
    }
    final_model = lgb.train(params, dtrain, callbacks=[lgb.log_evaluation(-1)])
    importances = final_model.feature_importance(importance_type="gain").tolist()
    feature_importances = dict(zip(feat_cols, importances, strict=True))

    if progress_cb:
        progress_cb(95, "Saving artifacts...")
    # 8. Write artifact
    ver = version or f"v{int(now.timestamp())}"
    model_dir = settings.ML_MODEL_DIR
    adir = artifact_dir(model_dir, ver)
    adir.mkdir(parents=True, exist_ok=True)

    final_model.save_model(str(artifact_model_path(model_dir, ver)))

    meta = ArtifactMeta(
        version=ver,
        feature_schema=feat_cols,
        label_schema=label_names,
        head=head,
        security_id=security_id,
        timeframe=timeframe,
        training_from=from_dt.date().isoformat(),
        training_to=to_dt.date().isoformat(),
        horizon=horizon,
        git_sha=settings.GIT_SHA,
    )
    meta.save(model_dir)

    report = {
        "version": ver,
        "cv_folds": cv_results,
        "cv_mean_accuracy": (
            round(sum(f["accuracy"] for f in cv_results) / len(cv_results), 4)
            if cv_results else None
        ),
        "feature_importances": {k: round(v, 2) for k, v in sorted(
            feature_importances.items(), key=lambda x: x[1], reverse=True
        )},
    }
    artifact_report_path(model_dir, ver).write_text(json.dumps(report, indent=2))

    log.info(
        "ml_train_done",
        version=ver,
        n_samples=len(feat_mat),
        cv_mean_acc=report["cv_mean_accuracy"],
    )
    return ver
