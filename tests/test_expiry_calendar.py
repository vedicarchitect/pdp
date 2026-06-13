"""Unit tests for the NIFTY expiry calendar (resolve_expiry arithmetic).

These use a synthetic expiry list so they run without the external abi-project DuckDB.
The list deliberately mixes weekdays (Thu/Wed/Tue) to prove the resolver is weekday-agnostic
and honours holiday-shifted expiries.
"""
from __future__ import annotations

from datetime import date

import pytest

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar

# Mixed-weekday weekly expiries incl. a holiday shift (2024-08-14 Wed) and the Thu→Tue move.
_WEEKLY = [
    date(2024, 8, 8),   # Thu
    date(2024, 8, 14),  # Wed  (Aug 15 holiday shift)
    date(2024, 8, 22),  # Thu
    date(2024, 8, 29),  # Thu
    date(2025, 9, 2),   # Tue  (post weekday-regime change)
    date(2025, 9, 9),   # Tue
]


@pytest.fixture()
def cal() -> NiftyExpiryCalendar:
    return NiftyExpiryCalendar({"WEEK": list(_WEEKLY), "MONTH": [date(2024, 8, 29)]})


def test_expiry_day_counts_as_code_1(cal: NiftyExpiryCalendar) -> None:
    assert cal.resolve_expiry(date(2024, 8, 8), "WEEK", 1) == date(2024, 8, 8)


def test_day_after_expiry_rolls_to_next(cal: NiftyExpiryCalendar) -> None:
    assert cal.resolve_expiry(date(2024, 8, 9), "WEEK", 1) == date(2024, 8, 14)


def test_holiday_shifted_expiry_resolved(cal: NiftyExpiryCalendar) -> None:
    # A trade day in the Aug-15-holiday week resolves to the shifted Wednesday expiry.
    assert cal.resolve_expiry(date(2024, 8, 12), "WEEK", 1) == date(2024, 8, 14)


def test_next_week_is_code_2(cal: NiftyExpiryCalendar) -> None:
    assert cal.resolve_expiry(date(2024, 8, 12), "WEEK", 2) == date(2024, 8, 22)


def test_weekday_regime_change_is_agnostic(cal: NiftyExpiryCalendar) -> None:
    # Tuesday-regime period resolves correctly with no weekday math.
    assert cal.resolve_expiry(date(2025, 9, 1), "WEEK", 1) == date(2025, 9, 2)


def test_out_of_range_returns_none(cal: NiftyExpiryCalendar) -> None:
    assert cal.resolve_expiry(date(2025, 9, 9), "WEEK", 2) is None  # nothing after last
    assert cal.resolve_expiry(date(2030, 1, 1), "WEEK", 1) is None


def test_invalid_code_raises(cal: NiftyExpiryCalendar) -> None:
    with pytest.raises(ValueError):
        cal.resolve_expiry(date(2024, 8, 8), "WEEK", 0)


def test_unknown_flag_returns_none(cal: NiftyExpiryCalendar) -> None:
    assert cal.resolve_expiry(date(2024, 8, 8), "QUARTER", 1) is None
