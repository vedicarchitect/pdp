"""dev-reload-scoping: ensure_port_free.py must not silently kill a live trading server.

`task dev` and `task dev:trade` both call this script to free port 8000. Before this change
it killed whatever held the port unconditionally, so running `task dev` in a second terminal
during a paper session silently terminated the strategy host mid-position (the 2026-07-09
incident's dev-tooling root cause). See openspec/changes/dev-reload-scoping/proposal.md.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import ensure_port_free  # noqa: E402


TRADING_CMDLINE = "uv run uvicorn pdp.main:app --host 0.0.0.0 --port 8000 --workers 1"
RELOAD_CMDLINE = "uv run uvicorn pdp.main:app --reload --reload-dir pdp --host 0.0.0.0 --port 8000"


def test_refuses_to_kill_trading_server_without_force(capsys):
    killed: list[int] = []

    rc = ensure_port_free.main(
        ["--port", "8000"],
        find_pids=lambda port: [111],
        command_line=lambda pid: TRADING_CMDLINE,
        kill=lambda pid: killed.append(pid),
        confirm=lambda prompt: "y",
    )

    assert rc != 0
    assert killed == []
    captured = capsys.readouterr()
    assert "111" in captured.err


def test_force_kills_trading_server():
    killed: list[int] = []

    rc = ensure_port_free.main(
        ["--port", "8000", "--force"],
        find_pids=lambda port: [111],
        command_line=lambda pid: TRADING_CMDLINE,
        kill=lambda pid: killed.append(pid),
        confirm=lambda prompt: (_ for _ in ()).throw(AssertionError("must not prompt under --force")),
    )

    assert rc == 0
    assert killed == [111]


def test_kills_stale_reload_server_without_force():
    killed: list[int] = []

    rc = ensure_port_free.main(
        ["--port", "8000", "--yes"],
        find_pids=lambda port: [222],
        command_line=lambda pid: RELOAD_CMDLINE,
        kill=lambda pid: killed.append(pid),
    )

    assert rc == 0
    assert killed == [222]


def test_no_holder_skips_process_inspection():
    inspected: list[int] = []

    rc = ensure_port_free.main(
        ["--port", "8000"],
        find_pids=lambda port: [],
        command_line=lambda pid: inspected.append(pid) or "unused",
        kill=lambda pid: (_ for _ in ()).throw(AssertionError("must not kill when port is free")),
    )

    assert rc == 0
    assert inspected == []
