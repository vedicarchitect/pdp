"""Unit tests for the period_levels family (PDH/PDL, PWH/PWL, PMH/PML)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pdp.indicators.period_levels import PeriodLevelsTracker


def _bar(t: PeriodLevelsTracker, day: datetime, high: float, low: float, close: float):
    return t.update(high, low, close, 0.0, day)


class TestPeriodLevelsDay:
    def test_pdh_pdl_frozen_on_new_day(self):
        t = PeriodLevelsTracker()
        d1 = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)  # Mon
        _bar(t, d1, 100, 90, 95)
        _bar(t, d1, 110, 92, 105)  # day1 H/L = 110/90
        # New day → freezes day1 as prior-day high/low
        st = _bar(t, d1 + timedelta(days=1), 120, 100, 115)
        assert st.pdh == 110
        assert st.pdl == 90

    def test_no_prior_until_boundary(self):
        t = PeriodLevelsTracker()
        d1 = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        st = _bar(t, d1, 100, 90, 95)
        assert st.pdh is None
        assert st.pdl is None


class TestPeriodLevelsWeekMonth:
    def test_pwh_pwl_frozen_on_new_week(self):
        t = PeriodLevelsTracker()
        # Week 25 (Mon-Tue 2026-06-15/16)
        _bar(t, datetime(2026, 6, 15, 4, 0, tzinfo=UTC), 100, 90, 95)
        _bar(t, datetime(2026, 6, 16, 4, 0, tzinfo=UTC), 130, 85, 120)  # week H/L = 130/85
        # Next ISO week (Mon 2026-06-22) → freeze prior week
        st = _bar(t, datetime(2026, 6, 22, 4, 0, tzinfo=UTC), 140, 110, 135)
        assert st.pwh == 130
        assert st.pwl == 85

    def test_pmh_pml_frozen_on_new_month(self):
        t = PeriodLevelsTracker()
        _bar(t, datetime(2026, 6, 10, 4, 0, tzinfo=UTC), 200, 180, 190)
        _bar(t, datetime(2026, 6, 25, 4, 0, tzinfo=UTC), 230, 170, 220)  # June H/L = 230/170
        # July → freeze June
        st = _bar(t, datetime(2026, 7, 1, 4, 0, tzinfo=UTC), 240, 210, 235)
        assert st.pmh == 230
        assert st.pml == 170


class TestPeriodLevelsNoBarTime:
    def test_none_bar_time_returns_state(self):
        t = PeriodLevelsTracker()
        st = t.update(100, 90, 95, 0.0, None)
        assert st is not None
        assert st.pdh is None
