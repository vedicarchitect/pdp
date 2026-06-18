### Requirement: Async job execution subsystem

The system SHALL provide a `JobRunner` that executes long-running tasks as `asyncio.Task`s, tracks state in a PostgreSQL `jobs` table (status: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED), and publishes progress via Redis pub/sub. CPU-bound operations SHALL be wrapped in `asyncio.to_thread()` to avoid blocking the event loop. The hot tick → WS path latency (p99 ≤ 50ms) SHALL NOT be impacted by running jobs.

#### Scenario: Submit and complete a job
- **WHEN** a job of type `validate_warehouse` is submitted via the API
- **THEN** a Job record is created with status `PENDING`, transitions to `RUNNING`, and upon completion transitions to `COMPLETED` with results stored in the `result` column

#### Scenario: Cancel a running job
- **WHEN** `POST /api/v1/jobs/{id}/cancel` is called on a running job
- **THEN** the asyncio.Task is cancelled, the job status becomes `CANCELLED`, and the WebSocket sends a final status message

#### Scenario: Job failure is recorded
- **WHEN** a job handler raises an unhandled exception
- **THEN** the job status becomes `FAILED`, the error message is stored in the `error` column, and the WebSocket sends the failure status

---

### Requirement: Job progress WebSocket

The system SHALL expose `/ws/jobs/{job_id}` WebSocket endpoint that streams progress updates (progress percentage 0–100 and human-readable message) in real-time. The WebSocket SHALL send a final message with the terminal status (COMPLETED/FAILED/CANCELLED) and then close.

#### Scenario: Live progress streaming
- **WHEN** a client connects to `/ws/jobs/{id}` for a running job
- **THEN** progress messages are received in real-time as `{"progress": 45, "message": "Processing 2026-03-15"}`

---

### Requirement: Job management REST API

The system SHALL expose: `GET /api/v1/jobs` (list jobs with optional filters: status, type, limit), `GET /api/v1/jobs/{id}` (job details with logs and result), `POST /api/v1/jobs/{id}/cancel` (cancel running job), `DELETE /api/v1/jobs/{id}` (delete completed/failed record).

#### Scenario: List running jobs
- **WHEN** `GET /api/v1/jobs?status=RUNNING` is called with two running jobs
- **THEN** HTTP 200 is returned with an array of two job objects

#### Scenario: Get job details with result
- **WHEN** `GET /api/v1/jobs/{id}` is called for a completed job
- **THEN** HTTP 200 is returned with status `COMPLETED` and the `result` field populated

---

### Requirement: Destructive operation confirmation

Destructive housekeeping operations (e.g., `reset-paper`) SHALL require `{"confirm": true}` in the request body. Without this parameter, the endpoint SHALL return HTTP 400 with a warning message describing the destructive action.

#### Scenario: Reset-paper without confirmation
- **WHEN** `POST /api/v1/housekeeping/reset-paper` is called without `{"confirm": true}`
- **THEN** HTTP 400 is returned with message "This operation will delete all paper orders, trades, and positions. Include confirm: true to proceed."

#### Scenario: Reset-paper with confirmation
- **WHEN** `POST /api/v1/housekeeping/reset-paper` is called with `{"confirm": true}`
- **THEN** the job is submitted and HTTP 200 is returned with the job record

---

### Requirement: Operations frontend

The system SHALL provide an `/operations` route with a job launcher (task type selector, dynamic parameter form, submit button) and a job history table (DataTable with columns: Type, Status, Progress, Duration, Actions). Running jobs SHALL show a live progress bar updated via WebSocket.

#### Scenario: Launch a job from the UI
- **WHEN** a user selects "Backfill Spot" from the launcher, enters date params, and clicks Launch
- **THEN** a job is created, appears in the job table as RUNNING, and the progress bar updates in real-time

#### Scenario: Cancel a job from the UI
- **WHEN** a user clicks Cancel on a running job row
- **THEN** the job status changes to CANCELLED in the table
