"""Backtest↔live parity test: same bar sequence → same ML signal at every bar."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pdp.market.bars import BarClosed
from pdp.ml.features import build_feature_row, build_feature_rows


def _bar(close: float, i: int = 0) -> BarClosed:
    t = datetime(2026, 6, 15, 4, 0, tzinfo=UTC) + timedelta(minutes=15 * i)
    c = Decimal(str(close))
    return BarClosed(
        security_id="13",
        timeframe="15m",
        bar_time=t,
        open=c,
        high=Decimal(str(close + 2)),
        low=Decimal(str(close - 2)),
        close=c,
        volume=1000,
        oi=0,
    )


class TestBacktestLiveParity:
    """Verify that the same bars produce identical feature rows whether processed
    as a batch (training / backtest path) or row-by-row (live inference path)."""

    def test_batch_vs_incremental_feature_rows_match(self):
        bars = [_bar(100.0 + i * 0.5, i) for i in range(20)]
        snaps = [None] * 20
        sts = [None] * 20

        # Batch path (training / backtest)
        batch_rows = build_feature_rows(bars, snaps, sts)

        # Incremental path (live inference — one row at a time)
        incremental_rows = []
        prev = None
        prev_macd_hist = 0.0
        for i, (bar, snap, st) in enumerate(zip(bars, snaps, sts, strict=True)):
            row = build_feature_row(bar, snap, st, prev_bar=prev)
            if i > 0:
                row["macd_histogram_slope"] = row["macd_histogram"] - prev_macd_hist
            prev_macd_hist = row["macd_histogram"]
            prev = bar
            incremental_rows.append(row)

        assert len(batch_rows) == len(incremental_rows)
        for i, (br, ir) in enumerate(zip(batch_rows, incremental_rows, strict=True)):
            for col in br:
                assert abs(br[col] - ir[col]) < 1e-9, (
                    f"Parity failure at bar {i}, column {col!r}: "
                    f"batch={br[col]}, live={ir[col]}"
                )

    def test_no_future_data_in_row_t(self):
        """Row t must be identical regardless of how many future bars exist."""
        n = 30
        bars = [_bar(100.0 + i, i) for i in range(n)]
        snaps = [None] * n
        sts = [None] * n

        rows_full = build_feature_rows(bars, snaps, sts)

        # Truncate at various horizons and check earlier rows are unchanged
        for cutoff in [10, 15, 20, 25]:
            rows_cut = build_feature_rows(bars[:cutoff], snaps[:cutoff], sts[:cutoff])
            for i in range(cutoff - 1):
                for col in rows_full[i]:
                    assert abs(rows_full[i][col] - rows_cut[i][col]) < 1e-9, (
                        f"Lookahead leak at bar {i} / cutoff {cutoff}, col {col!r}"
                    )
