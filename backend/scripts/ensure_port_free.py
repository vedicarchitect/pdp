"""Pre-flight guard for `task dev` / `task dev:trade`.

Windows lets a new process bind a port that's already LISTENING (SO_REUSEADDR
semantics differ from Linux), so a stale `uvicorn --reload` from a previous
session doesn't error out — it just silently starts a second listener and the
OS round-robins new connections across both. Once one of them is dead/stuck,
requests intermittently hang forever with no error on either side.

This script finds any process already listening on the target port and, if
found, prompts to kill it before the new server starts.
"""
from __future__ import annotations

import subprocess
import sys
from argparse import ArgumentParser


def _find_listening_pids_windows(port: int) -> list[int]:
    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, check=False
    ).stdout
    pids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP":
            continue
        local_addr, state, pid = parts[1], parts[3], parts[-1]
        if state != "LISTENING":
            continue
        if not local_addr.endswith(f":{port}"):
            continue
        try:
            pids.add(int(pid))
        except ValueError:
            continue
    return sorted(pids)


def _find_listening_pids_posix(port: int) -> list[int]:
    out = subprocess.run(
        ["lsof", "-t", "-i", f":{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return sorted({int(pid) for pid in out.split() if pid.strip().isdigit()})


def _command_line_windows(pid: int) -> str:
    out = subprocess.run(
        ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and ln.strip() != "CommandLine"]
    return lines[0] if lines else "<unknown>"


def _command_line_posix(pid: int) -> str:
    out = subprocess.run(
        ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout
    return out.strip() or "<unknown>"


def _kill_windows(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=False)


def _kill_posix(pid: int) -> None:
    subprocess.run(["kill", "-9", str(pid)], check=False)


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--yes", action="store_true", help="Kill stale listeners without prompting"
    )
    args = parser.parse_args()

    is_windows = sys.platform == "win32"
    find_pids = _find_listening_pids_windows if is_windows else _find_listening_pids_posix
    command_line = _command_line_windows if is_windows else _command_line_posix
    kill = _kill_windows if is_windows else _kill_posix

    pids = find_pids(args.port)
    if not pids:
        return 0

    print(f"Port {args.port} already has {len(pids)} listener(s) — likely a stale dev server:")
    for pid in pids:
        print(f"  PID {pid}: {command_line(pid)}")

    if not args.yes:
        reply = input(f"Kill these {len(pids)} process(es) and continue? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborting — resolve the port conflict manually, or re-run with --yes.")
            return 1

    for pid in pids:
        kill(pid)
    print(f"Killed {len(pids)} stale process(es). Starting fresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
