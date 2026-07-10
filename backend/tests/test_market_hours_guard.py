"""dev-reload-scoping: `task dev` must refuse to start a reload watcher during market hours.

A strategy holding positions has no business being restarted by a debugging tool. See
openspec/changes/dev-reload-scoping/proposal.md.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import guard_market_hours  # noqa: E402

_IST = ZoneInfo("Asia/Kolkata")


def test_blocks_mid_session_on_a_trading_day(capsys, monkeypatch):
    monkeypatch.delenv("PDP_ALLOW_RELOAD_IN_MARKET", raising=False)
    now = datetime(2026, 7, 10, 11, 0, tzinfo=_IST)  # Friday

    rc = guard_market_hours.main(now_ist=now, holiday_set=set())

    assert rc != 0
    assert "task dev:trade" in capsys.readouterr().err


def test_passes_outside_market_hours():
    now = datetime(2026, 7, 10, 20, 0, tzinfo=_IST)

    rc = guard_market_hours.main(now_ist=now, holiday_set=set())

    assert rc == 0


def test_override_passes_with_warning(capsys, monkeypatch):
    monkeypatch.setenv("PDP_ALLOW_RELOAD_IN_MARKET", "1")
    now = datetime(2026, 7, 10, 11, 0, tzinfo=_IST)

    rc = guard_market_hours.main(now_ist=now, holiday_set=set())

    assert rc == 0
    assert "WARNING" in capsys.readouterr().err


def test_weekend_passes_without_override():
    now = datetime(2026, 7, 11, 11, 0, tzinfo=_IST)  # Saturday

    rc = guard_market_hours.main(now_ist=now, holiday_set=set())

    assert rc == 0


def test_holiday_passes_without_override():
    now = datetime(2026, 7, 10, 11, 0, tzinfo=_IST)  # Friday, but flagged as a holiday

    rc = guard_market_hours.main(now_ist=now, holiday_set={now.date()})

    assert rc == 0
