"""Tests for scripts/trade_day.py's indicator-matrix validation harness
(indicator-matrix-kite-parity task 7): the extended `_indicator_lines` dump and the
`--expected` diff harness (`_run_validation`/`_flatten_expected`/`_flatten_live_cell`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from trade_day import (
    _flatten_expected,
    _flatten_live_cell,
    _indicator_lines,
    _run_validation,
)


def _sample_monitor() -> dict:
    return {
        "indicators": {
            "13": {
                "tf": {
                    "5m": {
                        "ema9": 24213.0,
                        "ema20": 24214.0,
                        "st_10_2": {"value": 24069.9, "direction": "down"},
                        "st_10_3": {"value": 24050.0, "direction": "down"},
                        "st_3_1": {"value": 24200.0, "direction": "up"},
                        "psar": 24075.0,
                        "rsi": 39.96,
                        "vwap": 24159.4,
                        "vwma": 24248.3,
                    },
                    "1D": {"ema9": None},
                },
                "camarilla_daily": {"r4": 24266.36, "r3": 24236.63, "s3": 24177.17, "s4": 24147.45},
                "camarilla_monthly": {"r4": 24573.05},
                "period": {"pdh": 24259.8, "pdl": 24000.2, "pmh": 24261.6, "pml": 23070.15},
            },
        },
    }


def test_indicator_lines_includes_st_variants_and_levels() -> None:
    lines = _indicator_lines(_sample_monitor())
    text = "\n".join(lines)
    assert "NIFTY indicators" in text
    assert "24069.9" in text or "24,069.9" in text  # ST(10,2) value rendered
    assert "PMH" in text
    assert "24261.6" in text or "24,261.6" in text
    assert "Camarilla(daily" in text
    assert "Camarilla(monthly" in text


def test_indicator_lines_empty_monitor_returns_no_lines() -> None:
    assert _indicator_lines(None) == []
    assert _indicator_lines({}) == []


def test_flatten_expected_walks_nested_st_variant_dicts() -> None:
    cell = {"ema9": 24213.0, "st_10_2": {"value": 24069.9, "direction": 1}}
    flat = _flatten_expected("13.tf.5m", cell)
    assert flat["13.tf.5m.ema9"] == 24213.0
    assert flat["13.tf.5m.st_10_2.value"] == 24069.9
    # direction is not numeric in the real payload ("up"/"down"), but this test's
    # int stand-in confirms flattening descends into nested dicts either way
    assert flat["13.tf.5m.st_10_2.direction"] == 1.0


def test_flatten_live_cell_extracts_only_requested_keys() -> None:
    live_cell = {
        "ema9": 24213.5,
        "st_10_2": {"value": 24070.0, "direction": "down"},
        "rsi": 40.0,
    }
    keys = {"13.tf.5m.ema9", "13.tf.5m.st_10_2.value"}
    flat = _flatten_live_cell("13.tf.5m", live_cell, keys)
    assert flat == {"13.tf.5m.ema9": 24213.5, "13.tf.5m.st_10_2.value": 24070.0}


def test_flatten_live_cell_missing_key_is_none() -> None:
    flat = _flatten_live_cell("13.tf.5m", {}, {"13.tf.5m.ema200"})
    assert flat == {"13.tf.5m.ema200": None}


def test_run_validation_passes_within_tolerance(tmp_path, capsys) -> None:
    expected = {
        "13": {
            "tf": {"5m": {"ema9": 24213.0, "ema20": 24214.0}},
        },
    }
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    exit_code = _run_validation(_sample_monitor(), str(expected_path), tolerance=1.0)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "cells matched" in out


def test_run_validation_fails_outside_tolerance(tmp_path, capsys) -> None:
    expected = {
        "13": {
            "tf": {"5m": {"ema9": 24000.0}},  # live is 24213.0 — 213pt off
        },
    }
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    exit_code = _run_validation(_sample_monitor(), str(expected_path), tolerance=1.0)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "diff" in out


def test_run_validation_reports_unseeded_as_failure(tmp_path, capsys) -> None:
    """A field the live cell doesn't have (ema200 unseeded) must fail loudly, not
    silently pass or be skipped."""
    expected = {
        "13": {
            "tf": {"5m": {"ema200": 24100.0}},
        },
    }
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    exit_code = _run_validation(_sample_monitor(), str(expected_path), tolerance=1.0)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "unseeded" in out


def test_run_validation_no_live_data_fails(tmp_path) -> None:
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps({}), encoding="utf-8")
    assert _run_validation(None, str(expected_path), tolerance=1.0) == 1
