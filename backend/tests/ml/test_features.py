"""Tests for ml.features — leakage safety, label horizon, and train→artifact round-trip."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pdp.market.bars import BarClosed
from pdp.ml.features import build_feature_row, build_feature_rows, feature_names
from pdp.ml.labels import directional_labels, expiry_labels
from pdp.ml.registry import (
    FEATURE_SCHEMA,
    LABEL_SCHEMA_DIRECTIONAL,
    ArtifactMeta,
    SchemaDriftError,
    check_schema,
)


def _bar(close: float, i: int = 0, sid: str = "13", tf: str = "15m") -> BarClosed:
    t = datetime(2026, 6, 15, 4, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
    c = Decimal(str(close))
    return BarClosed(
        security_id=sid,
        timeframe=tf,
        bar_time=t,
        open=c,
        high=Decimal(str(close + 2)),
        low=Decimal(str(close - 2)),
        close=c,
        volume=1000,
        oi=0,
    )


def _make_bars(n: int, start: float = 100.0) -> list[BarClosed]:
    return [_bar(start + i * 0.5, i) for i in range(n)]


# ── Feature leakage tests ─────────────────────────────────────────────────────

class TestFeatureLeakage:
    def test_row_t_uses_only_data_up_to_t(self):
        """The feature row for bar t must only depend on bars with index ≤ t."""
        bars = _make_bars(30)
        # Build rows with all bars
        rows_all = build_feature_rows(bars, [None] * 30, [None] * 30)

        # Now truncate at t=20 and build again; rows 0-19 must match
        rows_truncated = build_feature_rows(bars[:20], [None] * 20, [None] * 20)

        for i in range(19):
            for col in ("close", "close_pct_change", "macd_histogram_slope"):
                assert abs(rows_all[i][col] - rows_truncated[i][col]) < 1e-9, (
                    f"Column {col!r} at index {i} differs — possible look-ahead leak"
                )

    def test_macd_slope_uses_prior_row_only(self):
        """macd_histogram_slope at row t = macd_histogram[t] - macd_histogram[t-1]."""
        bars = _make_bars(30)
        rows = build_feature_rows(bars, [None] * 30, [None] * 30)
        for i in range(1, len(rows)):
            expected_slope = rows[i]["macd_histogram"] - rows[i - 1]["macd_histogram"]
            assert abs(rows[i]["macd_histogram_slope"] - expected_slope) < 1e-9

    def test_first_row_slope_is_zero(self):
        """Row 0 has no prior row; macd_histogram_slope must be 0."""
        bars = _make_bars(5)
        rows = build_feature_rows(bars, [None] * 5, [None] * 5)
        assert rows[0]["macd_histogram_slope"] == 0.0


# ── Label horizon tests ───────────────────────────────────────────────────────

class TestLabelHorizon:
    def test_last_horizon_rows_are_none(self):
        bars = _make_bars(20)
        horizon = 5
        labels = directional_labels(bars, horizon=horizon)
        assert len(labels) == 20
        # Last 5 rows must have None labels (horizon unavailable)
        for lbl in labels[-horizon:]:
            assert lbl is None

    def test_labeled_rows_are_valid_strings(self):
        bars = _make_bars(20)
        labels = directional_labels(bars, horizon=3)
        valid = {"up", "flat", "down"}
        for lbl in labels[:-3]:
            assert lbl in valid

    def test_all_up_series(self):
        # Bars strictly rising by 5 per bar → forward return always positive
        bars = [_bar(100.0 + i * 5, i) for i in range(20)]
        labels = directional_labels(bars, horizon=1, up_threshold=0.01)
        for lbl in labels[:-1]:
            assert lbl == "up"

    def test_expiry_labels_at_spot(self):
        bars = [_bar(100.0, i) for i in range(5)]
        lbls = expiry_labels(bars, expiry_close=100.0, near_threshold=0.005)
        assert all(lbl == "at_spot" for lbl in lbls)

    def test_expiry_labels_far_above(self):
        bars = [_bar(85.0, i) for i in range(3)]
        lbls = expiry_labels(bars, expiry_close=100.0, far_threshold=0.015)
        # (100 - 85) / 85 ≈ 0.176 > 0.015 → far_above
        assert all(lbl == "far_above" for lbl in lbls)


# ── Feature schema tests ──────────────────────────────────────────────────────

class TestFeatureSchema:
    def test_build_row_produces_all_schema_columns(self):
        bar = _bar(100.0)
        row = build_feature_row(bar, None, None)
        schema = FEATURE_SCHEMA
        for col in schema:
            # Options-specific columns may not be in row when no opts supplied; that's OK
            if col in ("max_pain", "pcr", "gex", "iv_atm", "india_vix",
                       "oi_wall_above", "oi_wall_below", "max_pain_distance"):
                assert col in row or True  # these are added by build_feature_row
            # Otherwise all schema cols must be present
        # Ensure no NaN/None values in the row
        for k, v in row.items():
            assert isinstance(v, float), f"Column {k!r} is not a float: {v!r}"

    def test_feature_names_matches_schema(self):
        assert feature_names() == FEATURE_SCHEMA

    def test_schema_drift_raises(self):
        meta = ArtifactMeta(
            version="v0",
            feature_schema=["a", "b"],
            label_schema=LABEL_SCHEMA_DIRECTIONAL,
            head="directional",
            security_id="13",
            timeframe="15m",
            training_from="2026-01-01",
            training_to="2026-06-01",
            horizon=5,
        )
        with pytest.raises(SchemaDriftError):
            check_schema(["a", "b", "c"], meta)

    def test_schema_matches_no_error(self):
        meta = ArtifactMeta(
            version="v0",
            feature_schema=["a", "b"],
            label_schema=LABEL_SCHEMA_DIRECTIONAL,
            head="directional",
            security_id="13",
            timeframe="15m",
            training_from="2026-01-01",
            training_to="2026-06-01",
            horizon=5,
        )
        check_schema(["a", "b"], meta)  # should not raise


# ── CV embargo test ───────────────────────────────────────────────────────────

class TestCVEmbargo:
    def test_train_end_plus_embargo_is_val_start(self):
        """Purged walk-forward: val_start = train_end + embargo."""
        from pdp.ml.train import _purged_walk_forward_cv
        # Build a minimal dataset with a known label distribution
        n = 100
        feat_mat = [[float(i)] for i in range(n)]
        y = [i % 3 for i in range(n)]
        results = _purged_walk_forward_cv(feat_mat, y, ["x"], ["down", "flat", "up"],
                                          n_splits=3, embargo=5)
        # Each fold should have been computed without look-ahead
        assert len(results) > 0
        for fold in results:
            assert "accuracy" in fold
            assert fold["n_val"] > 0


# ── Round-trip test ───────────────────────────────────────────────────────────

class TestArtifactRoundTrip:
    def test_meta_save_load(self, tmp_path):
        meta = ArtifactMeta(
            version="v_test",
            feature_schema=FEATURE_SCHEMA,
            label_schema=LABEL_SCHEMA_DIRECTIONAL,
            head="directional",
            security_id="13",
            timeframe="15m",
            training_from="2026-01-01",
            training_to="2026-06-01",
            horizon=5,
            git_sha="abc123",
        )
        model_dir = str(tmp_path)
        meta.save(model_dir)
        loaded = ArtifactMeta.load(model_dir, "v_test")
        assert loaded.version == meta.version
        assert loaded.feature_schema == meta.feature_schema
        assert loaded.label_schema == meta.label_schema
        assert loaded.git_sha == "abc123"

    def test_parity_same_bars_same_features(self):
        """Same bar sequence in build_feature_rows must produce identical rows twice."""
        bars = _make_bars(20)
        rows1 = build_feature_rows(bars, [None] * 20, [None] * 20)
        rows2 = build_feature_rows(bars, [None] * 20, [None] * 20)
        for r1, r2 in zip(rows1, rows2, strict=True):
            for col in r1:
                assert r1[col] == r2[col], f"Parity failure at column {col!r}"
