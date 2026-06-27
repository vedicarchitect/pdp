"""Tests for the phase-2 expiry head: options-feature leakage + expiry-head round-trip."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pdp.market.bars import BarClosed
from pdp.ml.features import build_feature_row, build_feature_rows
from pdp.ml.labels import expiry_labels
from pdp.ml.registry import LABEL_SCHEMA_EXPIRY


def _bar(close: float, i: int = 0) -> BarClosed:
    t = datetime(2026, 6, 15, 4, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
    c = Decimal(str(close))
    return BarClosed(
        security_id="13", timeframe="15m", bar_time=t,
        open=c, high=Decimal(str(close + 2)), low=Decimal(str(close - 2)),
        close=c, volume=1000, oi=0,
    )


class TestOptionsFeatureLeakage:
    def test_options_features_default_zero_when_not_provided(self):
        bar = _bar(100.0)
        row = build_feature_row(bar, None, None, options_features=None)
        for col in ("max_pain", "pcr", "gex", "iv_atm", "india_vix"):
            assert col in row
            assert row[col] == 0.0

    def test_options_features_are_passthrough_values(self):
        bar = _bar(100.0)
        opts = {"max_pain": 18500.0, "pcr": 1.2, "gex": -500000.0}
        row = build_feature_row(bar, None, None, options_features=opts)
        assert row["max_pain"] == 18500.0
        assert row["pcr"] == 1.2
        assert row["gex"] == -500000.0

    def test_options_features_not_in_prior_row(self):
        """Options features for bar t do not affect bar t-1 (no reverse leak)."""
        bars = [_bar(100.0 + i, i) for i in range(5)]
        # Row at i=3 gets options features; rows 0-2 must be unaffected
        opts_list = [None, None, None, {"max_pain": 18500.0}, None]
        rows_with = build_feature_rows(bars, [None]*5, [None]*5, opts_list)
        rows_without = build_feature_rows(bars, [None]*5, [None]*5, None)
        # Rows 0-2 must match (options at i=3 must not leak back)
        for i in range(3):
            assert rows_with[i]["max_pain"] == rows_without[i]["max_pain"] == 0.0


class TestExpiryLabels:
    def test_at_spot_bucket(self):
        bars = [_bar(100.0, i) for i in range(5)]
        lbls = expiry_labels(bars, expiry_close=100.0)
        assert all(lbl == "at_spot" for lbl in lbls)

    def test_far_below_bucket(self):
        bars = [_bar(120.0, i) for i in range(3)]
        # expiry_close=100, current=120 → (100-120)/120 = -0.167 < -far_threshold=0.015
        lbls = expiry_labels(bars, expiry_close=100.0, far_threshold=0.015)
        assert all(lbl == "far_below" for lbl in lbls)

    def test_far_above_bucket(self):
        bars = [_bar(80.0, i) for i in range(3)]
        # expiry_close=100, current=80 → (100-80)/80 = 0.25 > far_threshold=0.015
        lbls = expiry_labels(bars, expiry_close=100.0, far_threshold=0.015)
        assert all(lbl == "far_above" for lbl in lbls)

    def test_label_schema_matches_registry(self):
        assert LABEL_SCHEMA_EXPIRY == ["far_below", "near_below", "at_spot", "near_above", "far_above"]

    def test_zero_close_returns_none(self):
        from decimal import Decimal
        bar = BarClosed(
            security_id="13", timeframe="15m", bar_time=datetime(2026, 6, 15, 4, 0, tzinfo=UTC),
            open=Decimal("0"), high=Decimal("0"), low=Decimal("0"), close=Decimal("0"),
            volume=0, oi=0,
        )
        lbls = expiry_labels([bar], expiry_close=100.0)
        assert lbls[0] is None


class TestExpiryHeadGating:
    def test_expiry_head_disabled_by_default(self):
        # The default must be disabled
        # (We don't call get_settings() in tests to avoid requiring a real .env;
        #  instead we directly check the Settings class default)
        from pdp.settings import Settings

        # Just check the field default exists in the class definition
        fields = Settings.model_fields
        assert "ML_EXPIRY_HEAD_ENABLED" in fields
        assert fields["ML_EXPIRY_HEAD_ENABLED"].default is False
