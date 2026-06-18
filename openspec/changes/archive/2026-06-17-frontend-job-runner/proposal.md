## Why

ML training, backtests, and housekeeping tasks (backfill, reset-paper, validate-warehouse) are all CLI-only via `Taskfile.yml` and `scripts/`. The user wants to trigger, monitor, and manage these from the frontend with live progress — eliminating the need to SSH or open a terminal. Additionally, the options strategy backtester (proposal #4) needs an async execution path for large date ranges that would time out as synchronous API calls.

## What Changes

- **Async job subsystem `src/pdp/jobs/`**: A job runner that executes tasks as `asyncio.Task`s, tracks status/progress/logs in PostgreSQL (`jobs` table), and publishes progress via Redis pub/sub to a WebSocket endpoint `/ws/jobs/{job_id}`. Job states: `PENDING → RUNNING → COMPLETED | FAILED | CANCELLED`.
- **ML API endpoints**: `POST /api/v1/ml/train` (submit ML training job), `GET /api/v1/ml/models` (list trained models), `POST /api/v1/ml/deploy/{version}` (set active model). These wrap the existing `src/pdp/ml/train.py` and `src/pdp/ml/registry.py` — refactor CLI scripts into importable async functions.
- **Housekeeping API endpoints**: `POST /api/v1/housekeeping/{task}` for tasks: `backfill-spot`, `backfill-options`, `reset-paper`, `snapshot-instruments`, `validate-warehouse`. Destructive operations (`reset-paper`) require a `confirm: true` body parameter. These wrap existing `Taskfile.yml` / `scripts/` logic — refactor into importable functions.
- **Frontend `/operations` admin page**: Job launcher (select task, configure params, submit), live job table (status, progress bar, duration, logs), cancel button for running jobs.

## Capabilities

### New Capabilities
- `job-runner`: Async job execution subsystem with PostgreSQL tracking, Redis progress pub/sub, and WebSocket live updates.
- `ml-api`: REST endpoints for ML model training, listing, and deployment.
- `housekeeping-api`: REST endpoints for housekeeping tasks (backfill, reset, validation).

### Modified Capabilities
- `backtest`: `POST /api/v1/backtests/run` can optionally submit as an async job via the job runner.

## Impact

- `src/pdp/jobs/__init__.py` — NEW
- `src/pdp/jobs/models.py` — NEW (Job PostgreSQL model)
- `src/pdp/jobs/runner.py` — NEW (JobRunner class)
- `src/pdp/jobs/routes.py` — NEW (job management endpoints)
- `src/pdp/jobs/ws.py` — NEW (WebSocket handler for live progress)
- `src/pdp/ml/routes.py` — NEW (ML API endpoints)
- `src/pdp/ml/train.py` — MODIFIED (refactor CLI entry point into importable async function)
- `src/pdp/housekeeping/__init__.py` — NEW
- `src/pdp/housekeeping/routes.py` — NEW (housekeeping endpoints)
- `src/pdp/housekeeping/tasks.py` — NEW (importable wrappers for existing scripts)
- `src/pdp/main.py` — MODIFIED (register job/ml/housekeeping routers, start JobRunner)
- `alembic/versions/xxx_add_jobs_table.py` — NEW (migration)
- `tests/jobs/test_runner.py` — NEW
- `tests/ml/test_routes.py` — NEW
- `tests/housekeeping/test_routes.py` — NEW
- `frontend/src/routes/operations.tsx` — NEW
- `frontend/src/components/operations/JobLauncher.tsx` — NEW
- `frontend/src/components/operations/JobTable.tsx` — NEW
- `frontend/src/components/operations/JobProgress.tsx` — NEW
- `frontend/src/hooks/useJobWS.ts` — NEW
- `frontend/src/components/Sidebar.tsx` — MODIFIED (add Operations link)
