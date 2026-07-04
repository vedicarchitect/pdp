"""Tests for symbol plumbing job→CLI in pdp.housekeeping.tasks (no subprocess spawned)."""
from __future__ import annotations

from uuid import uuid4

import pdp.housekeeping.tasks as tasks


def test_repo_root_resolves_to_backend_scripts_dir():
    """tasks.py lives at backend/pdp/housekeeping/tasks.py; _REPO_ROOT must point at backend/,
    where scripts/ actually lives (post repo-restructure), not the outer repo root."""
    assert (tasks._REPO_ROOT / "scripts" / "backfill_spot.py").exists()


async def _capture_run_script(monkeypatch):
    calls: list[tuple[str, list[str]]] = []

    async def _fake_run_script(job_id, script_path, args, progress_cb):
        calls.append((script_path, args))
        return {"lines_total": 0, "log_tail": []}

    monkeypatch.setattr(tasks, "_run_script", _fake_run_script)
    return calls


async def _noop_progress(job_id, pct, msg):
    pass


async def test_backfill_spot_defaults_symbol_to_nifty(monkeypatch):
    calls = await _capture_run_script(monkeypatch)
    await tasks.backfill_spot(uuid4(), {"from": "2026-01-01"}, _noop_progress)
    script, args = calls[0]
    assert script == "scripts/backfill_spot.py"
    assert args[:2] == ["--symbol", "NIFTY"]
    assert "--from" in args and "2026-01-01" in args


async def test_backfill_spot_passes_through_symbol(monkeypatch):
    calls = await _capture_run_script(monkeypatch)
    await tasks.backfill_spot(uuid4(), {"symbol": "BANKNIFTY", "only_missing": True}, _noop_progress)
    _, args = calls[0]
    assert args[:2] == ["--symbol", "BANKNIFTY"]
    assert "--only-missing" in args


async def test_backfill_options_passes_through_symbol(monkeypatch):
    calls = await _capture_run_script(monkeypatch)
    await tasks.backfill_options(uuid4(), {"symbol": "SENSEX", "from": "2026-06-01"}, _noop_progress)
    script, args = calls[0]
    assert script == "scripts/backfill_options_gap.py"
    assert args[:2] == ["--symbol", "SENSEX"]


async def test_backfill_levels_passes_through_symbol(monkeypatch):
    calls = await _capture_run_script(monkeypatch)
    await tasks.backfill_levels(uuid4(), {"symbol": "BANKNIFTY", "only_missing": True}, _noop_progress)
    script, args = calls[0]
    assert script == "scripts/backfill_levels.py"
    assert args[:2] == ["--symbol", "BANKNIFTY"]
    assert "--only-missing" in args


async def test_backfill_vix_has_no_symbol_arg(monkeypatch):
    calls = await _capture_run_script(monkeypatch)
    await tasks.backfill_vix(uuid4(), {"from": "2026-01-01", "resolve": True}, _noop_progress)
    script, args = calls[0]
    assert script == "scripts/backfill_vix.py"
    assert "--symbol" not in args
    assert "--resolve" in args
