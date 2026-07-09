"""Unit tests for the shared DTE window helper (strangle-live-dte-window).

`within_dte` is the single gate used by BOTH the backtest walk-forward and the
live DirectionalStrangle entry gate, so live/backtest parity depends on it.
"""

from __future__ import annotations

from datetime import date

from pdp.instruments.expiry_calendar import dte, within_dte


def test_dte_counts_calendar_days():
    assert dte(date(2026, 7, 9), date(2026, 7, 14)) == 5
    assert dte(date(2026, 7, 14), date(2026, 7, 14)) == 0  # expiry day itself


def test_within_dte_none_max_is_no_filter():
    # dte_max=None → always allowed (default behaviour, filter disabled)
    assert within_dte(date(2026, 1, 1), date(2026, 12, 31), None) is True


def test_within_dte_none_expiry_passes_through():
    # Unresolved expiry is a data gap the caller handles elsewhere — not a DTE reject.
    assert within_dte(date(2026, 7, 9), None, 15) is True


def test_within_dte_inside_window_inclusive_boundary():
    expiry = date(2026, 7, 14)
    # Exactly dte_max days out → allowed (<= is inclusive).
    assert within_dte(date(2026, 6, 29), expiry, 15) is True  # 15 days
    # One day too far → blocked.
    assert within_dte(date(2026, 6, 28), expiry, 15) is False  # 16 days


def test_within_dte_expiry_day_allowed():
    expiry = date(2026, 7, 14)
    assert within_dte(expiry, expiry, 15) is True  # dte=0 <= 15
