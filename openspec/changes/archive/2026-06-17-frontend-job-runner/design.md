## Context

PDP's long-running operations are currently CLI-only:
- **ML training**: `src/pdp/ml/train.py` — invoked via `task ml:train` or `uv run python -m pdp.ml.train`
- **ML inference**: `src/pdp/ml/infer.py` — used by strategy host internally
- **Backfill**: `scripts/backfill_nifty_spot.py`, `scripts/backfill_option_bars.py` — via `task backfill:spot`, `task backfill:options`
- **Housekeeping**: `task reset-paper`, `task validate:warehouse`, `task audit:coverage`

These scripts are standalone entry points that import from the `pdp` package. To make them API-callable, they need to be refactored into importable async functions that can be invoked by a job runner.

The API process runs as a single uvicorn worker. Long-running jobs (ML training, large backtests) must NOT block the hot tick → WS path (p99 ≤ 50ms latency rule). Jobs run as `asyncio.Task`s in the same process but yield cooperatively via `await asyncio.sleep(0)` at progress checkpoints.

## Goals / Non-Goals

**Goals:**
- Run ML training, backtests, and housekeeping from the frontend.
- Track job status, progress, and logs in PostgreSQL.
- Stream live progress to the frontend via WebSocket.
- Gate destructive operations (reset-paper) with explicit confirmation.
- Keep the tick→WS hot path unblocked.

**Non-Goals:**
- Multi-process job workers (Celery, RQ) — overkill for a single-user platform.
- Job scheduling / cron (future enhancement).
- Job chaining / DAGs (future enhancement).
- Multi-tenant job isolation (single user).

## Decisions

### D1: Jobs table in PostgreSQL

```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(50) NOT NULL,          -- 'ml_train', 'backtest', 'backfill_spot', etc.
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    params JSONB NOT NULL DEFAULT '{}',  -- task-specific parameters
    progress INTEGER DEFAULT 0,          -- 0-100
    progress_message TEXT,               -- human-readable progress update
    result JSONB,                        -- task output (success data or error details)
    logs TEXT,                           -- accumulated log output
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT                           -- error message on failure
);
```

### D2: JobRunner as asyncio.Task manager

```python
class JobRunner:
    def __init__(self, db_session_factory, redis):
        self._tasks: dict[UUID, asyncio.Task] = {}

    async def submit(self, job_type: str, params: dict) -> Job:
        job = Job(type=job_type, params=params, status="PENDING")
        # persist to DB
        task = asyncio.create_task(self._execute(job))
        self._tasks[job.id] = task
        return job

    async def _execute(self, job: Job):
        job.status = "RUNNING"
        job.started_at = utcnow()
        try:
            handler = self._handlers[job.type]
            result = await handler(job.params, progress_callback=self._on_progress)
            job.status = "COMPLETED"
            job.result = result
        except asyncio.CancelledError:
            job.status = "CANCELLED"
        except Exception as e:
            job.status = "FAILED"
            job.error = str(e)
        finally:
            job.completed_at = utcnow()
            # persist final state

    async def cancel(self, job_id: UUID):
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
```

### D3: Progress pub/sub via Redis

Progress updates are published to `job:{job_id}:progress` Redis channel. The WebSocket handler subscribes and forwards to the frontend.

```python
async def _on_progress(self, job_id: UUID, progress: int, message: str):
    await self._redis.publish(f"job:{job_id}:progress", json.dumps({
        "progress": progress,
        "message": message,
    }))
    # Also update DB periodically (every 10% or every 5s)
```

### D4: Handler registration

Each job type registers a handler function:

```python
HANDLERS = {
    "ml_train": ml_train_handler,
    "backtest_options": options_backtest_handler,
    "backfill_spot": backfill_spot_handler,
    "backfill_options": backfill_options_handler,
    "reset_paper": reset_paper_handler,
    "validate_warehouse": validate_warehouse_handler,
    "snapshot_instruments": snapshot_instruments_handler,
}
```

Handlers are async functions that accept `(params: dict, progress_callback)` and return a result dict.

### D5: Script refactoring pattern

Existing scripts are refactored by extracting the core logic into an importable async function:

```python
# Before (scripts/backfill_nifty_spot.py):
if __name__ == "__main__":
    args = parse_args()
    backfill(args.from_date, args.to_date, ...)

# After:
async def backfill_spot(from_date, to_date, only_missing=False, progress_cb=None):
    """Importable entry point for the job runner."""
    ...
    if progress_cb:
        await progress_cb(job_id, pct, f"Processing {date}")
    ...

# CLI still works:
if __name__ == "__main__":
    args = parse_args()
    asyncio.run(backfill_spot(args.from_date, ...))
```

### D6: Destructive operation gating

`reset-paper` and any future destructive operations require `{"confirm": true}` in the request body. Without it, the endpoint returns HTTP 400 with a warning message.

### D7: Latency protection

Jobs run as `asyncio.Task`s and yield at progress checkpoints. CPU-bound operations (ML training, heavy pandas/polars computation) are wrapped in `asyncio.to_thread()` to avoid blocking the event loop:

```python
result = await asyncio.to_thread(train_model_sync, params)
```

### D8: Frontend operations page layout

```
┌──────────────────────────────────────────┐
│ Operations                               │
├──────────────────────────────────────────┤
│ Launch Job                               │
│ ┌────────────────────────────────────┐   │
│ │ Task: [▼ ML Train / Backfill / ...]│   │
│ │ Params: (dynamic per task type)    │   │
│ │ [▶ Launch]                         │   │
│ └────────────────────────────────────┘   │
├──────────────────────────────────────────┤
│ Job History                              │
│ ┌────────────────────────────────────┐   │
│ │ ID  │ Type │ Status │ Progress │ ⏱ │   │
│ │ a1  │ ML   │ ██████ 60% │ 2m    │   │
│ │ b2  │ BF   │ ✓ Done     │ 5m    │   │
│ │ c3  │ BT   │ ✗ Failed   │ 1m    │   │
│ │ [Cancel] [View Logs]            │   │
│ └────────────────────────────────────┘   │
└──────────────────────────────────────────┘
```

## Risks / Trade-offs

- **Single-process jobs**: Long-running CPU-bound jobs could impact API responsiveness despite `to_thread`. Monitor and consider a separate worker process if needed. Document as a known limitation.
- **Job table growth**: Old job records accumulate. Add a retention policy (delete completed jobs older than 30 days) as a housekeeping task itself.
- **Script refactoring scope**: Some scripts may have complex CLI argument parsing or interactive prompts. Refactoring must preserve CLI functionality while adding the importable entry point.

## Migration Plan

1. Create `jobs/` module with models, runner, routes, and WebSocket handler.
2. Alembic migration for `jobs` table.
3. Create `housekeeping/` module with task wrappers.
4. Refactor ML scripts into importable functions.
5. Create ML API routes.
6. Register all routers in `main.py`.
7. Build frontend operations page.
8. Wire WebSocket for live progress.

## Open Questions

- None — architecture follows existing patterns (lifespan background tasks, Redis pub/sub, PostgreSQL persistence).
