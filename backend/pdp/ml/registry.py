"""ML registry — feature schema, label schema, and versioned artifact path contract.

The registry is the single source of truth for:
- Which feature columns the model expects (``FEATURE_SCHEMA``).
- Which label buckets the model predicts (``LABEL_SCHEMA``).
- Artifact file layout and version naming.
- Schema-drift detection: comparing a live feature set against the artifact's recorded schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ── Feature schema ─────────────────────────────────────────────────────────────
# Ordered list of feature column names produced by features.py.
# Adding, removing, or reordering entries here constitutes a schema bump and
# requires retraining before the new schema can be served.

FEATURE_SCHEMA: list[str] = [
    # --- price structure ---
    "close",
    "high",
    "low",
    "open",
    "bar_range",
    "body",
    "upper_shadow",
    "lower_shadow",
    "close_pct_change",
    "high_pct_change",
    # --- EMA suite ---
    "ema_9",
    "ema_20",
    "ema_50",
    "close_vs_ema9",
    "close_vs_ema20",
    "close_vs_ema50",
    "ema9_slope",
    "ema20_slope",
    # --- RSI ---
    "rsi",
    "rsi_ma",
    # --- VWAP ---
    "close_vs_vwap",
    # --- SuperTrend ---
    "st_direction",
    # --- MACD ---
    "macd",
    "macd_signal",
    "macd_histogram",
    "macd_histogram_slope",
    # --- Candlestick ---
    "cs_signal",
    "cs_doji",
    "cs_hammer",
    "cs_shooting_star",
    "cs_bullish_engulfing",
    "cs_bearish_engulfing",
    "cs_bullish_harami",
    "cs_bearish_harami",
    "cs_morning_star",
    "cs_evening_star",
    "cs_bullish_marubozu",
    "cs_bearish_marubozu",
    # --- Elliott Wave ---
    "ew_trend",
    "ew_confidence",
    # --- Fibonacci levels ---
    "fib_distance",
    "fib_nearest_level",
    # --- Elder Impulse ---
    "elder_regime_green",
    "elder_regime_red",
    "elder_ema13_rising",
    "elder_macd_hist_rising",
    # --- Pivot levels ---
    "close_vs_pp",
    "close_vs_r1",
    "close_vs_s1",
]

# ── Label schema ───────────────────────────────────────────────────────────────
# Directional head: 3-class bucketed forward return
LABEL_SCHEMA_DIRECTIONAL: list[str] = ["down", "flat", "up"]

# Expiry head: 5-class expiry-close-zone bucketed distance from spot
LABEL_SCHEMA_EXPIRY: list[str] = ["far_below", "near_below", "at_spot", "near_above", "far_above"]


# ── Artifact layout ────────────────────────────────────────────────────────────


def artifact_dir(model_dir: str, version: str) -> Path:
    """Return the versioned artifact directory path."""
    return Path(model_dir) / version


def artifact_model_path(model_dir: str, version: str) -> Path:
    return artifact_dir(model_dir, version) / "model.lgb"


def artifact_meta_path(model_dir: str, version: str) -> Path:
    return artifact_dir(model_dir, version) / "meta.json"


def artifact_report_path(model_dir: str, version: str) -> Path:
    return artifact_dir(model_dir, version) / "report.json"


# ── Artifact metadata ──────────────────────────────────────────────────────────


@dataclass
class ArtifactMeta:
    version: str
    feature_schema: list[str]
    label_schema: list[str]
    head: str  # "directional" or "expiry"
    security_id: str
    timeframe: str
    training_from: str  # ISO date
    training_to: str  # ISO date
    horizon: int  # bars ahead used for label
    git_sha: str = "local"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "feature_schema": self.feature_schema,
            "label_schema": self.label_schema,
            "head": self.head,
            "security_id": self.security_id,
            "timeframe": self.timeframe,
            "training_from": self.training_from,
            "training_to": self.training_to,
            "horizon": self.horizon,
            "git_sha": self.git_sha,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ArtifactMeta:
        return cls(
            version=d["version"],
            feature_schema=d["feature_schema"],
            label_schema=d["label_schema"],
            head=d["head"],
            security_id=d["security_id"],
            timeframe=d["timeframe"],
            training_from=d["training_from"],
            training_to=d["training_to"],
            horizon=d["horizon"],
            git_sha=d.get("git_sha", "local"),
            extra={
                k: v
                for k, v in d.items()
                if k
                not in {
                    "version",
                    "feature_schema",
                    "label_schema",
                    "head",
                    "security_id",
                    "timeframe",
                    "training_from",
                    "training_to",
                    "horizon",
                    "git_sha",
                }
            },
        )

    def save(self, model_dir: str) -> None:
        p = artifact_meta_path(model_dir, self.version)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, model_dir: str, version: str) -> ArtifactMeta:
        p = artifact_meta_path(model_dir, version)
        return cls.from_dict(json.loads(p.read_text()))


# ── Drift guard ────────────────────────────────────────────────────────────────


class SchemaDriftError(Exception):
    """Raised when the live feature schema does not match the artifact's schema."""


def check_schema(live_features: list[str], artifact_meta: ArtifactMeta) -> None:
    """Raise SchemaDriftError if live feature list differs from the artifact's schema.

    Only column identity and order matter — values are not inspected here.
    """
    if live_features != artifact_meta.feature_schema:
        extra = set(live_features) - set(artifact_meta.feature_schema)
        missing = set(artifact_meta.feature_schema) - set(live_features)
        raise SchemaDriftError(
            f"Feature schema drift detected for artifact {artifact_meta.version!r}. "
            f"Extra in live: {sorted(extra)}. Missing from live: {sorted(missing)}."
        )


# ── Active Model Management ──────────────────────────────────────────────────


def get_active_model_version(model_dir: str) -> str | None:
    active_link = Path(model_dir) / "active.txt"
    if active_link.exists():
        return active_link.read_text().strip()
    return None


def set_active_model(model_dir: str, version: str) -> None:
    active_link = Path(model_dir) / "active.txt"
    active_link.parent.mkdir(parents=True, exist_ok=True)
    active_link.write_text(version)


def list_artifacts(model_dir: str) -> list[tuple[ArtifactMeta, dict]]:
    base_dir = Path(model_dir)
    if not base_dir.exists():
        return []

    results = []
    for d in base_dir.iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            try:
                meta = ArtifactMeta.load(model_dir, d.name)
                report_path = d / "report.json"
                report = json.loads(report_path.read_text()) if report_path.exists() else {}
                results.append((meta, report))
            except Exception:
                pass

    # Sort by version descending
    results.sort(key=lambda x: x[0].version, reverse=True)
    return results
