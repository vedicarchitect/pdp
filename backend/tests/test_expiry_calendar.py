"""Unit tests for the NIFTY expiry calendar (resolve_expiry arithmetic).

Uses a synthetic in-memory expiry list — no external data needed.
The list deliberately mixes weekdays (Thu/Wed/Tue) to prove the resolver is weekday-agnostic
and honours holiday-shifted expiries.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pdp.instruments.expiry_calendar import (
    NiftyExpiryCalendar,
    classify_month_expiries,
    expiry_cadence_gaps,
    expiry_cadence_threshold,
    load_expiry_calendar_from_db,
    upsert_confirmed_expiries,
)

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


# ── expiry_cadence_gaps ──────────────────────────────────────────────────────


def test_missing_weekly_expiry_is_flagged_as_cadence_gap() -> None:
    # NIFTY weekly cadence; two consecutive claimed expiries 21 days apart (2 weeks missing).
    expiries = [date(2023, 2, 2), date(2023, 2, 23), date(2023, 3, 2)]
    gaps = expiry_cadence_gaps("NIFTY", expiries)
    assert gaps == [("NIFTY", date(2023, 2, 2), date(2023, 2, 23), 21)]


def test_normal_weekly_cadence_is_not_flagged() -> None:
    expiries = [date(2023, 2, 2), date(2023, 2, 9), date(2023, 2, 16)]
    assert expiry_cadence_gaps("NIFTY", expiries) == []


def test_monthly_only_underlying_normal_cadence_is_not_flagged() -> None:
    # A hypothetical monthly-only underlying (via explicit cadence override, since none of
    # NIFTY/BANKNIFTY/SENSEX's *stored* option_bars history is actually monthly-cadence —
    # see _EXPECTED_CADENCE's note); 30 days apart is normal, not a gap.
    expiries = [date(2024, 11, 27), date(2024, 12, 27), date(2025, 1, 29)]
    gaps = expiry_cadence_gaps("SOME_MONTHLY_INDEX", expiries, cadence_days=35, tolerance_days=5)
    assert gaps == []


def test_monthly_only_underlying_still_flags_a_real_gap() -> None:
    # Two consecutive monthly expiries ~70 days apart — a real missing month.
    expiries = [date(2024, 11, 27), date(2025, 2, 5)]
    gaps = expiry_cadence_gaps("SOME_MONTHLY_INDEX", expiries, cadence_days=35, tolerance_days=5)
    assert len(gaps) == 1
    assert gaps[0][0] == "SOME_MONTHLY_INDEX"
    assert gaps[0][3] == 70


def test_banknifty_is_treated_as_weekly_cadence() -> None:
    # BANKNIFTY's *stored* option_bars distinct-expiry history stays weekly-cadence right
    # through 2026-07 despite the real-world forward-listing monthly-only regime change — see
    # _EXPECTED_CADENCE's note. A 21-day gap must still be flagged for BANKNIFTY, same as NIFTY.
    expiries = [date(2023, 2, 2), date(2023, 2, 23), date(2023, 3, 2)]
    gaps = expiry_cadence_gaps("BANKNIFTY", expiries)
    assert gaps == [("BANKNIFTY", date(2023, 2, 2), date(2023, 2, 23), 21)]


def test_cadence_threshold_defaults_to_weekly_for_unknown_underlying() -> None:
    assert expiry_cadence_threshold("SOMETHING_NEW") == expiry_cadence_threshold("NIFTY")


# ── classify_month_expiries ──────────────────────────────────────────────────


def test_classify_month_expiries_picks_last_of_calendar_month() -> None:
    exps = [
        date(2023, 3, 2), date(2023, 3, 9), date(2023, 3, 16), date(2023, 3, 30),  # Mar
        date(2023, 4, 6), date(2023, 4, 27),                                        # Apr
    ]
    week, month = classify_month_expiries(exps)
    assert week == sorted(exps)                       # WEEK = every expiry
    assert month == [date(2023, 3, 30), date(2023, 4, 27)]  # last-of-month only


def test_classify_month_expiries_dedupes_and_sorts_unsorted_input() -> None:
    week, month = classify_month_expiries(
        [date(2023, 5, 25), date(2023, 5, 4), date(2023, 5, 25)]
    )
    assert week == [date(2023, 5, 4), date(2023, 5, 25)]
    assert month == [date(2023, 5, 25)]


# ── DB-backed confirmed-expiry store (fakes; no Mongo) ───────────────────────


class _FakeFindCol:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, query: dict):
        return [d for d in self._docs if d["underlying"] == query.get("underlying")]


class _FakeUpsertCol:
    def __init__(self) -> None:
        self.ops = None

    def bulk_write(self, ops, ordered=True):
        self.ops = ops

        class _Result:
            upserted_count = len(ops)

        return _Result()


class _FakeMdb:
    def __init__(self, col) -> None:
        self._col = col

    def __getitem__(self, _name):
        return self._col


def test_load_expiry_calendar_from_db_builds_per_flag_and_filters_underlying() -> None:
    docs = [
        {"underlying": "NIFTY", "flag": "WEEK", "expiry_date": datetime(2023, 3, 16)},
        {"underlying": "NIFTY", "flag": "WEEK", "expiry_date": datetime(2023, 3, 23)},
        {"underlying": "NIFTY", "flag": "MONTH", "expiry_date": datetime(2023, 3, 30)},
        {"underlying": "BANKNIFTY", "flag": "WEEK", "expiry_date": datetime(2023, 3, 29)},
    ]
    cal = load_expiry_calendar_from_db(_FakeMdb(_FakeFindCol(docs)), "NIFTY")
    assert cal.resolve_expiry(date(2023, 3, 16), "WEEK", 1) == date(2023, 3, 16)
    assert cal.resolve_expiry(date(2023, 3, 17), "WEEK", 1) == date(2023, 3, 23)
    assert cal.resolve_expiry(date(2023, 3, 17), "MONTH", 1) == date(2023, 3, 30)
    # BANKNIFTY's expiry was filtered out of a NIFTY calendar.
    assert date(2023, 3, 29) not in cal.expiries("WEEK")


def test_upsert_confirmed_expiries_counts_new_and_skips_empty() -> None:
    col = _FakeUpsertCol()
    n = upsert_confirmed_expiries(
        _FakeMdb(col), "NIFTY", "WEEK", [date(2023, 3, 16), date(2023, 3, 23)], source="test"
    )
    assert n == 2
    assert col.ops is not None and len(col.ops) == 2

    empty = _FakeUpsertCol()
    assert upsert_confirmed_expiries(_FakeMdb(empty), "NIFTY", "WEEK", [], source="test") == 0
    assert empty.ops is None  # no bulk_write issued for an empty list


def test_upsert_confirmed_expiries_stamps_weekday_and_lot() -> None:
    col = _FakeUpsertCol()
    # 2023-03-23 is a Thursday (weekday 3); supply a lot for it but not for 2023-03-30.
    upsert_confirmed_expiries(
        _FakeMdb(col), "NIFTY", "WEEK", [date(2023, 3, 23), date(2023, 3, 30)],
        source="nse_archive", lot_by_date={date(2023, 3, 23): 50},
    )
    assert col.ops is not None
    by_date = {op._filter["expiry_date"]: op._doc["$set"] for op in col.ops}
    thu = by_date[datetime(2023, 3, 23)]
    assert thu["expiry_weekday"] == "Thursday" and thu["expiry_weekday_num"] == 3
    assert thu["lot_size"] == 50
    # No lot supplied for the 30th -> weekday stamped, lot_size left absent (never guessed).
    assert "lot_size" not in by_date[datetime(2023, 3, 30)]
