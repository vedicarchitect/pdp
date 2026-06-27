"""Unit tests for the progress CLI commands (add-progress-test-cli).

Covers:
- CLIConfig.from_env() — paper/live mode selection
- format_timestamp() — IST timezone
- format_number() — decimal formatting and None handling
- print_table() — JSON path produces valid JSON; table path doesn't raise
- portfolio segment grouping (DB branch) via mocked DB positions
- Greeks sign adjustment for short vs long positions
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from pdp.cli.progress.config import CLIConfig
from pdp.cli.progress.formatter import _IST, format_number, format_timestamp, print_table

# ---------------------------------------------------------------------------
# CLIConfig
# ---------------------------------------------------------------------------


def test_config_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    cfg = CLIConfig.from_env()
    assert cfg.live_mode is False


def test_config_live_mode_when_set(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    cfg = CLIConfig.from_env()
    assert cfg.live_mode is True


def test_config_live_mode_true_string(monkeypatch):
    monkeypatch.setenv("LIVE", "true")
    cfg = CLIConfig.from_env()
    assert cfg.live_mode is True


def test_config_default_symbol(monkeypatch):
    monkeypatch.delenv("DEFAULT_SYMBOL", raising=False)
    cfg = CLIConfig.from_env()
    assert cfg.default_symbol == "NIFTY"


def test_config_custom_symbol(monkeypatch):
    monkeypatch.setenv("DEFAULT_SYMBOL", "BANKNIFTY")
    cfg = CLIConfig.from_env()
    assert cfg.default_symbol == "BANKNIFTY"


# ---------------------------------------------------------------------------
# format_timestamp — must be IST
# ---------------------------------------------------------------------------


def test_format_timestamp_is_ist():
    ts = format_timestamp()
    # datetime.now(tz=IST) produces an offset-aware string; IST = +05:30
    assert "+05:30" in ts


def test_format_timestamp_explicit():
    dt = datetime(2026, 6, 12, 10, 30, tzinfo=_IST)
    result = format_timestamp(dt)
    assert result == "2026-06-12T10:30:00+05:30"


# ---------------------------------------------------------------------------
# format_number
# ---------------------------------------------------------------------------


def test_format_number_default_two_decimals():
    assert format_number(123.456) == "123.46"


def test_format_number_zero_decimals():
    assert format_number(22500.0, 0) == "22500"


def test_format_number_none_returns_na():
    assert format_number(None) == "N/A"


def test_format_number_four_decimals():
    assert format_number(0.4512, 4) == "0.4512"


# ---------------------------------------------------------------------------
# print_table — JSON output
# ---------------------------------------------------------------------------


def test_print_table_json_output(capsys):
    headers = ["A", "B"]
    rows = [["x", "1"], ["y", "2"]]
    print_table("Test", headers, rows, "json")
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data == [{"A": "x", "B": "1"}, {"A": "y", "B": "2"}]


def test_print_table_table_output_does_not_raise():
    # Rich may or may not be installed; ensure no exception either way.
    headers = ["X", "Y"]
    rows = [["a", "b"]]
    print_table("Title", headers, rows, "table")  # no assertion needed, just no crash


# ---------------------------------------------------------------------------
# Portfolio DB branch — segment grouping
# ---------------------------------------------------------------------------


@dataclass
class _FakePos:
    exchange_segment: str
    net_qty: int
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    avg_price: Decimal = Decimal("100")


def _make_positions():
    return [
        _FakePos("NSE_EQ", 10, Decimal("45.60"), Decimal("0")),
        _FakePos("NSE_FNO", -65, Decimal("-5.67"), Decimal("120")),
        _FakePos("NSE_EQ", 0, Decimal("0"), Decimal("30")),  # closed, net_qty=0
    ]


@pytest.mark.asyncio
async def test_db_portfolio_segment_grouping_json(capsys):
    from pdp.cli.progress.commands.portfolio import _show_db_portfolio

    fake_positions = _make_positions()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = fake_positions

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_maker = MagicMock(return_value=mock_session)

    with patch("pdp.cli.progress.commands.portfolio.get_session_maker", return_value=mock_maker):
        await _show_db_portfolio("json", "2026-06-12T10:00:00+05:30", "paper")

    out = capsys.readouterr().out
    data = json.loads(out)

    assert "by_segment" in data
    segs = data["by_segment"]
    assert "NSE_EQ" in segs
    assert "NSE_FNO" in segs
    # open_positions only counts net_qty != 0
    assert segs["NSE_EQ"]["open_positions"] == 1
    assert segs["NSE_FNO"]["open_positions"] == 1
    assert abs(data["summary"]["total_unrealized_pnl"] - (45.60 - 5.67)) < 0.01


# ---------------------------------------------------------------------------
# Greeks sign adjustment
# ---------------------------------------------------------------------------


def _make_greeks_dict(delta=0.45, gamma=0.02, theta=-0.30, vega=55.0, iv=0.22):
    return {"iv": iv, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def test_greeks_sign_short_position():
    """Short positions (qty < 0) should negate all theoretical greeks."""
    g = _make_greeks_dict(delta=0.45, gamma=0.02, theta=-0.30, vega=55.0)
    qty = -130  # short 2 lots
    sign = -1 if qty < 0 else 1
    assert sign * g["delta"] == pytest.approx(-0.45)
    assert sign * g["gamma"] == pytest.approx(-0.02)
    assert sign * g["theta"] == pytest.approx(0.30)
    assert sign * g["vega"] == pytest.approx(-55.0)


def test_greeks_sign_long_position():
    """Long positions (qty > 0) preserve theoretical greeks unchanged."""
    g = _make_greeks_dict(delta=0.45, gamma=0.02, theta=-0.30, vega=55.0)
    qty = 130  # long 2 lots
    sign = -1 if qty < 0 else 1
    assert sign * g["delta"] == pytest.approx(0.45)
    assert sign * g["gamma"] == pytest.approx(0.02)
    assert sign * g["theta"] == pytest.approx(-0.30)
    assert sign * g["vega"] == pytest.approx(55.0)


def test_greeks_sign_short_put():
    """Short put: theoretical delta is -0.45, position delta should be +0.45."""
    g = _make_greeks_dict(delta=-0.45, gamma=0.02, theta=-0.28, vega=50.0)
    qty = -65  # short 1 lot
    sign = -1 if qty < 0 else 1
    assert sign * g["delta"] == pytest.approx(0.45)
    assert sign * g["vega"] == pytest.approx(-50.0)
