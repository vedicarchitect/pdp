"""Online inference — load artifact once, produce MLSignalState per bar.

Schema-drift guard: if the live feature schema does not match the artifact's
recorded schema, inference refuses to serve and returns None rather than a
silently wrong value.

Usage:
    loader = ModelLoader(model_dir="data/models", version="v1")
    loader.load()                            # called once at startup
    state = loader.infer(bar, snapshot, st)  # called per closed bar; None if not ready
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pdp.indicators.snapshot import Snapshot
    from pdp.indicators.supertrend import SuperTrendState
    from pdp.market.bars import BarClosed

log = structlog.get_logger()


@dataclass(slots=True)
class MLSignalState:
    """Read-only output of the ML inference layer for one (sid, tf) bar close."""
    probs: dict[str, float]   # label -> probability (sum ≈ 1.0)
    argmax: str               # label with highest probability
    version: str              # artifact version string


class ModelLoader:
    """Loads a versioned LightGBM artifact and exposes per-bar inference.

    A single instance is held per (security_id, timeframe, head) and its
    state is updated via ``infer()`` after each bar close.  No blocking I/O
    is performed on the hot path — the model is loaded once at startup.
    """

    __slots__ = ("_head", "_meta", "_model", "_model_dir", "_ready", "_version")

    def __init__(self, model_dir: str, version: str, head: str = "directional") -> None:
        self._model_dir = model_dir
        self._version = version
        self._head = head
        self._model: Any = None
        self._meta: Any = None
        self._ready = False

    @property
    def version(self) -> str:
        return self._version

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> None:
        """Load the artifact from disk.  Logs and sets ready=False on failure."""
        try:
            import lightgbm as lgb

            from pdp.ml.registry import ArtifactMeta, artifact_model_path
            meta = ArtifactMeta.load(self._model_dir, self._version)
            model = lgb.Booster(model_file=str(artifact_model_path(self._model_dir, self._version)))
            self._meta = meta
            self._model = model
            self._ready = True
            log.info("ml_model_loaded", version=self._version, head=self._head,
                     features=len(meta.feature_schema), labels=meta.label_schema)
        except Exception as exc:
            log.warning("ml_model_load_failed", version=self._version, exc=str(exc))
            self._ready = False

    def infer(
        self,
        bar: BarClosed,
        snapshot: Snapshot | None,
        supertrend: SuperTrendState | None,
        prev_bar: BarClosed | None = None,
        options_features: dict[str, float] | None = None,
    ) -> MLSignalState | None:
        """Produce an MLSignalState for the just-closed bar, or None on any failure.

        Reuses the already-computed ``snapshot`` — does not recompute indicators.
        No blocking I/O is performed here.
        """
        if not self._ready or self._model is None or self._meta is None:
            return None

        try:
            import numpy as np

            from pdp.ml.features import build_feature_row, feature_names
            from pdp.ml.registry import SchemaDriftError, check_schema

            live_cols = feature_names()
            try:
                check_schema(live_cols, self._meta)
            except SchemaDriftError as exc:
                log.warning("ml_schema_drift", version=self._version, detail=str(exc))
                self._ready = False
                return None

            row = build_feature_row(bar, snapshot, supertrend, prev_bar, options_features)
            x = np.array([[row.get(col, 0.0) for col in live_cols]], dtype=np.float32)
            raw_probs = self._model.predict(x)[0]

            labels = self._meta.label_schema
            probs = {lbl: float(p) for lbl, p in zip(labels, raw_probs, strict=False)}
            argmax = labels[int(raw_probs.argmax())]

            return MLSignalState(probs=probs, argmax=argmax, version=self._version)

        except Exception as exc:
            log.warning("ml_infer_error", version=self._version, exc=str(exc))
            return None


# ── Registry of active loaders ────────────────────────────────────────────────
# Keyed by (security_id, timeframe, head). Populated at startup by the strategy
# host or the ML serving layer; looked up per bar in the tick router.

_LOADERS: dict[tuple[str, str, str], ModelLoader] = {}


def register_loader(
    security_id: str,
    timeframe: str,
    loader: ModelLoader,
    head: str = "directional",
) -> None:
    """Register a (pre-loaded) ModelLoader for (sid, tf, head)."""
    _LOADERS[(security_id, timeframe, head)] = loader


def get_loader(
    security_id: str, timeframe: str, head: str = "directional"
) -> ModelLoader | None:
    return _LOADERS.get((security_id, timeframe, head))


def infer_all(
    security_id: str,
    timeframe: str,
    bar: BarClosed,
    snapshot: Snapshot | None,
    supertrend: SuperTrendState | None,
    prev_bar: BarClosed | None = None,
) -> dict[str, MLSignalState]:
    """Run all registered loaders for (sid, tf) and return {head: MLSignalState}."""
    results: dict[str, MLSignalState] = {}
    for (sid, tf, head), loader in _LOADERS.items():
        if sid == security_id and tf == timeframe:
            state = loader.infer(bar, snapshot, supertrend, prev_bar)
            if state is not None:
                results[head] = state
    return results
