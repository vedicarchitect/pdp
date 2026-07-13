"""Refuse to start the file-watching dev server during live market hours.

`task dev` restarts the backend on every source edit. A strategy holding positions has no
business being restarted by a debugging tool — see `task dev:trade` for a stable server.
This guard is the first command in the `dev` task; `dev:trade` does not run it.

Usage:
  python scripts/guard_market_hours.py
  PDP_ALLOW_RELOAD_IN_MARKET=1 python scripts/guard_market_hours.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from pdp.options.gap_backfill import holidays as _holidays
from pdp.settings import get_settings

_IST = ZoneInfo("Asia/Kolkata")
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)
_OVERRIDE_ENV = "PDP_ALLOW_RELOAD_IN_MARKET"


def is_market_hours(now_ist: datetime, holiday_set: set[date]) -> bool:
    """True when `now_ist` falls inside a trading session: weekday, non-holiday, 09:15-15:30."""
    d = now_ist.date()
    if d.weekday() >= 5 or d in holiday_set:
        return False
    return _MARKET_OPEN <= now_ist.time() < _MARKET_CLOSE


def main(now_ist: datetime | None = None, holiday_set: set[date] | None = None) -> int:
    now_ist = now_ist or datetime.now(_IST)
    if holiday_set is None:
        holiday_set = _holidays(get_settings().NSE_HOLIDAYS_JSON)

    if not is_market_hours(now_ist, holiday_set):
        return 0

    if os.environ.get(_OVERRIDE_ENV) == "1":
        print(
            f"WARNING: reload watcher starting during market hours ({now_ist:%H:%M} IST) — "
            f"{_OVERRIDE_ENV}=1 set.",
            file=sys.stderr,
        )
        return 0

    print(
        f"Refusing to start `task dev` at {now_ist:%H:%M} IST — market is open (09:15-15:30).\n"
        f"Use `task dev:trade` for a stable, non-reloading server during trading hours.\n"
        f"Set {_OVERRIDE_ENV}=1 to override.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
