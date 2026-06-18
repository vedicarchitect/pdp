## 1. Database migration

- [x] 1.1 Generate Alembic migration: `alembic revision --autogenerate -m "add jobs table"`
- [x] 1.2 Review migration — verify `jobs` table with columns: id (UUID PK), type, status, params (JSONB), progress, progress_message, result (JSONB), logs, created_at, started_at, completed_at, error
- [x] 1.3 Run `alembic upgrade head` — migration applies cleanly

## 2. Job runner core

- [x] 2.1 Create `src/pdp/jobs/__init__.py`
- [x] 2.2 Create `src/pdp/jobs/models.py` — SQLAlchemy model for `jobs` table, `JobStatus` enum
- [x] 2.3 Create `src/pdp/jobs/runner.py` — `JobRunner` class with `submit()`, `cancel()`, `_execute()`, `_on_progress()`, handler registry
- [x] 2.4 Implement `submit(job_type, params)` — create Job record, spawn `asyncio.Task`, return Job
- [x] 2.5 Implement `_execute(job)` — run handler, update status, catch CancelledError and exceptions
- [x] 2.6 Implement `cancel(job_id)` — cancel the asyncio.Task, update status to CANCELLED
- [x] 2.7 Implement progress callback — publish to Redis `job:{job_id}:progress`, update DB periodically

## 3. Job REST endpoints

- [x] 3.1 Create `src/pdp/jobs/routes.py` — FastAPI router under `/api/v1/jobs`
- [x] 3.2 `GET /api/v1/jobs` — list jobs, query params: `status`, `type`, `limit` (default 50)
- [x] 3.3 `GET /api/v1/jobs/{id}` — get job details including logs and result
- [x] 3.4 `POST /api/v1/jobs/{id}/cancel` — cancel a running job
- [x] 3.5 `DELETE /api/v1/jobs/{id}` — delete a completed/failed job record

## 4. Job WebSocket

- [x] 4.1 Create `src/pdp/jobs/ws.py` — WebSocket handler at `/ws/jobs/{job_id}`
- [x] 4.2 Subscribe to Redis `job:{job_id}:progress` channel
- [x] 4.3 Forward progress messages to connected WebSocket clients
- [x] 4.4 Send final status message (COMPLETED/FAILED/CANCELLED) and close

## 5. Housekeeping module

- [x] 5.1 Create `src/pdp/housekeeping/__init__.py`
- [x] 5.2 Create `src/pdp/housekeeping/tasks.py` — importable async wrappers for existing scripts:
  - [x] 5.2.1 `backfill_spot(from_date, to_date, only_missing, progress_cb)` — wraps `scripts/backfill_nifty_spot.py`
  - [x] 5.2.2 `backfill_options(from_date, to_date, codes, band, only_missing, progress_cb)` — wraps `scripts/backfill_option_bars.py`
  - [x] 5.2.3 `reset_paper(progress_cb)` — wraps `task reset-paper` logic
  - [x] 5.2.4 `validate_warehouse(progress_cb)` — wraps `task validate:warehouse` logic
  - [x] 5.2.5 `snapshot_instruments(progress_cb)` — wraps `task instruments:snapshot` logic
- [x] 5.3 Create `src/pdp/housekeeping/routes.py` — `POST /api/v1/housekeeping/{task}` for each task; `reset-paper` requires `{"confirm": true}`
- [x] 5.4 Register handlers in `JobRunner` (instance-based via `app.state.job_runner`)

## 6. ML API endpoints

- [x] 6.1 Refactor `src/pdp/ml/train.py` — extract core training logic into `async def train_model(params, progress_cb)` importable function; keep CLI `__main__` intact
- [x] 6.2 Create `src/pdp/ml/routes.py` — FastAPI router under `/api/v1/ml`
- [x] 6.3 `POST /api/v1/ml/train` — submit ML training job via JobRunner
- [x] 6.4 `GET /api/v1/ml/models` — list trained models from `src/pdp/ml/registry.py`
- [x] 6.5 `POST /api/v1/ml/deploy/{version}` — set active model version
- [x] 6.6 Register ML training handler in `JobRunner`

## 7. Main.py integration

- [x] 7.1 Register `jobs.routes.router` in `src/pdp/main.py`
- [x] 7.2 Register `ml.routes.router` in `src/pdp/main.py`
- [x] 7.3 Register `housekeeping.routes.router` in `src/pdp/main.py`
- [x] 7.4 Start `JobRunner` in `main.py` lifespan context (stored as `app.state.job_runner`)
- [x] 7.5 Register `/ws/jobs/{job_id}` WebSocket endpoint

## 8. Tests

- [x] 8.1 Create `tests/jobs/test_runner.py` — test submit, execute, cancel, progress
- [x] 8.2 Test job transitions: PENDING → RUNNING → COMPLETED
- [x] 8.3 Test job cancellation: RUNNING → CANCELLED
- [x] 8.4 Test job failure: RUNNING → FAILED with error message
- [x] 8.5 Test destructive operation gating: `reset-paper` without `confirm: true` returns 400
- [x] 8.6 Run `pytest tests/jobs/ -v` — all pass

## 9. Frontend operations page

- [x] 9.1 Create `frontend/src/routes/operations.tsx` — `createFileRoute('/operations')` with operations layout
- [x] 9.2 Create `frontend/src/components/operations/JobLauncher.tsx` — task type selector, dynamic params form per task, launch button
- [x] 9.3 Create `frontend/src/components/operations/JobTable.tsx` — DataTable of jobs: ID, Type, Status (Badge), Progress (progress bar), Duration, Actions (Cancel/View Logs)
- [x] 9.4 Create `frontend/src/components/operations/JobProgress.tsx` — progress bar with percentage and message
- [x] 9.5 Create `frontend/src/hooks/useJobWS.ts` — WebSocket hook for `/ws/jobs/{job_id}` with auto-reconnect
- [x] 9.6 Wire cancel button: `POST /api/v1/jobs/{id}/cancel`
- [x] 9.7 Add "Operations" link to sidebar under SYSTEM group (icon: `Settings` from lucide)

## 10. Confirmation dialog for destructive operations

- [x] 10.1 When launching `reset-paper`, show a confirmation Dialog: "This will delete all paper orders, trades, and positions. Are you sure?"
- [x] 10.2 Only send `{"confirm": true}` after user confirms
- [x] 10.3 Display danger Badge on destructive task types in the launcher

## 11. Final verification

- [x] 11.1 Run `alembic upgrade head` — jobs table created
- [x] 11.2 Run `pytest tests/ -v` — all tests pass
- [x] 11.3 Run `cd frontend && npm run build` — clean build ✓
- [x] 11.4 E2E: launch a `validate-warehouse` job from `/operations`, observe progress via WebSocket, verify COMPLETED status in job table
