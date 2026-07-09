from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

# Resolve script paths relative to the backend root regardless of CWD at runtime.
# tasks.py lives at backend/pdp/housekeeping/tasks.py → parents[2] = backend/.
_REPO_ROOT = Path(__file__).parents[2]


async def _run_script(
    job_id: UUID,
    script_path: str,
    args: list[str],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    await progress_cb(job_id, 0, f"Starting {script_path}...")

    abs_script = str(_REPO_ROOT / script_path)
    cmd = ["uv", "run", "python", abs_script] + args
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    logs: deque[str] = deque(maxlen=500)  # cap memory; store tail only
    line_count = 0

    try:
        if process.stdout:
            async for line in process.stdout:
                decoded = line.decode().strip()
                if decoded:
                    logs.append(decoded)
                    line_count += 1
                    prog_val = min(90, 5 + (line_count * 2))
                    if line_count % 10 == 1:
                        await progress_cb(job_id, prog_val, decoded[-100:])

        await process.wait()

    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise

    if process.returncode != 0:
        error_msg = "\n".join(list(logs)[-10:])
        raise RuntimeError(f"Script failed with exit code {process.returncode}:\n{error_msg}")

    await progress_cb(job_id, 100, "Completed successfully")
    return {"lines_total": line_count, "log_tail": list(logs)}


def _date_arg(params: dict[str, Any], key: str, alias: str) -> str | None:
    """Accept both spec-canonical key (e.g. 'from') and legacy alias ('from_date')."""
    return params.get(key) or params.get(alias)


async def backfill_spot(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    args: list[str] = ["--symbol", params.get("symbol") or "NIFTY"]
    if val := _date_arg(params, "from", "from_date"):
        args.extend(["--from", val])
    if val := _date_arg(params, "to", "to_date"):
        args.extend(["--to", val])
    if params.get("only_missing"):
        args.append("--only-missing")
    if params.get("dry_run"):
        args.append("--dry-run")
    return await _run_script(job_id, "scripts/backfill_spot.py", args, progress_cb)


async def backfill_options(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    args: list[str] = ["--symbol", params.get("symbol") or "NIFTY"]
    if val := _date_arg(params, "from", "from_date"):
        args.extend(["--from", val])
    if val := _date_arg(params, "to", "to_date"):
        args.extend(["--to", val])
    if "codes" in params:
        args.extend(["--codes", params["codes"]])
    if "band" in params:
        args.extend(["--band", str(params["band"])])
    if params.get("only_missing"):
        args.append("--only-missing")
    if params.get("dry_run"):
        args.append("--dry-run")
    return await _run_script(job_id, "scripts/backfill_options_gap.py", args, progress_cb)


async def backfill_levels(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    args: list[str] = ["--symbol", params.get("symbol") or "NIFTY"]
    if val := _date_arg(params, "from", "from_date"):
        args.extend(["--from", val])
    if val := _date_arg(params, "to", "to_date"):
        args.extend(["--to", val])
    if params.get("only_missing"):
        args.append("--only-missing")
    if params.get("dry_run"):
        args.append("--dry-run")
    return await _run_script(job_id, "scripts/backfill_levels.py", args, progress_cb)


async def backfill_vix(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    args: list[str] = []
    if val := _date_arg(params, "from", "from_date"):
        args.extend(["--from", val])
    if val := _date_arg(params, "to", "to_date"):
        args.extend(["--to", val])
    if params.get("vix_sid"):
        args.extend(["--vix-sid", str(params["vix_sid"])])
    if params.get("resolve"):
        args.append("--resolve")
    if params.get("only_missing"):
        args.append("--only-missing")
    if params.get("dry_run"):
        args.append("--dry-run")
    return await _run_script(job_id, "scripts/backfill_vix.py", args, progress_cb)


async def reset_paper(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    # Defensive second check — routes.py gates this, but guard here too in case
    # the handler is invoked directly via JobRunner.
    if not params.get("confirm"):
        raise ValueError("reset_paper requires confirm=True")
    return await _run_script(job_id, "scripts/reset_paper.py", [], progress_cb)


async def validate_warehouse(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    return await _run_script(job_id, "scripts/validate_options_warehouse.py", [], progress_cb)


async def snapshot_instruments(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    return await _run_script(job_id, "scripts/snapshot_instruments.py", [], progress_cb)
