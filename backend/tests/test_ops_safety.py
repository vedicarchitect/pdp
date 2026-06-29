"""Unit tests for ops-safety-net: redaction, errors.jsonl sink, feed_halt gate."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pdp.logging import _REDACT_MARKER, _ErrorsJsonlSink, sensitive_data_filter
from pdp.risk.feed_halt import FeedStaleHalt

# ── sensitive_data_filter ─────────────────────────────────────────────────────

def _apply(event_dict):
    return sensitive_data_filter(None, "info", event_dict)


def test_redact_access_token_key():
    out = _apply({"access_token": "secret123", "event": "test"})
    assert out["access_token"] == _REDACT_MARKER


def test_redact_api_key():
    out = _apply({"api_key": "mySuperKey", "event": "test"})
    assert out["api_key"] == _REDACT_MARKER


def test_redact_password():
    out = _apply({"password": "hunter2", "event": "test"})
    assert out["password"] == _REDACT_MARKER


def test_redact_bearer():
    out = _apply({"bearer": "sometoken", "event": "test"})
    assert out["bearer"] == _REDACT_MARKER


def test_redact_jwt_value():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = _apply({"token_value": jwt, "event": "test"})
    assert out["token_value"] == _REDACT_MARKER


def test_no_redact_unrelated_key():
    out = _apply({"strategy_id": "st_nifty", "event": "order_placed"})
    assert out["strategy_id"] == "st_nifty"


def test_no_redact_non_string_value():
    out = _apply({"some_count": 42, "event": "test"})
    assert out["some_count"] == 42


# ── _ErrorsJsonlSink ──────────────────────────────────────────────────────────

def test_errors_jsonl_appends_error_level():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "errors.jsonl")
        sink = _ErrorsJsonlSink(path, max_lines=100)
        event = {"level": "error", "event": "something_bad", "exc": "oops"}
        sink(None, "error", event)
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "something_bad"


def test_errors_jsonl_noop_for_info():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "errors.jsonl")
        sink = _ErrorsJsonlSink(path, max_lines=100)
        sink(None, "info", {"level": "info", "event": "just_info"})
        assert not Path(path).exists()


def test_errors_jsonl_truncate_on_startup():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "errors.jsonl"
        # Write 5 lines
        path.write_text("\n".join(f'{{"n":{i}}}' for i in range(5)) + "\n")
        sink = _ErrorsJsonlSink(str(path), max_lines=3)
        sink.truncate_on_startup()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["n"] == 2  # last 3 kept


# ── FeedStaleHalt ─────────────────────────────────────────────────────────────

def test_feed_halt_not_blocked_initially():
    halt = FeedStaleHalt(halt_after_seconds=5)
    assert halt.live_blocked is False


def test_feed_halt_engages_after_threshold():

    halt = FeedStaleHalt(halt_after_seconds=0)
    halt.on_feed_stale()
    # With halt_after=0 it should engage immediately on next call
    halt.on_feed_stale()
    assert halt.live_blocked is True


def test_feed_halt_clear_resumes():
    halt = FeedStaleHalt(halt_after_seconds=0)
    halt.on_feed_stale()
    halt.on_feed_stale()
    assert halt.live_blocked is True
    halt.clear()
    assert halt.live_blocked is False


def test_feed_halt_recovery_clears_timer_not_halt():
    halt = FeedStaleHalt(halt_after_seconds=0)
    halt.on_feed_stale()
    halt.on_feed_stale()
    assert halt.live_blocked is True
    halt.on_feed_recovered()
    # halt remains until operator clears it
    assert halt.live_blocked is True

def test_redact_nested_dict():
    out = _apply({"event": "test", "context": {"api_key": "mySuperKey", "nested": [{"password": "abc", "safe": 123}]}})
    assert out["context"]["api_key"] == _REDACT_MARKER
    assert out["context"]["nested"][0]["password"] == _REDACT_MARKER
    assert out["context"]["nested"][0]["safe"] == 123
