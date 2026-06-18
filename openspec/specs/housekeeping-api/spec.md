### Requirement: Housekeeping REST API

The system SHALL expose `POST /api/v1/housekeeping/{task}` for tasks: `backfill-spot`, `backfill-options`, `reset-paper`, `snapshot-instruments`, `validate-warehouse`. Each endpoint SHALL submit the task as an async job via the job runner and return the job record. Task-specific parameters SHALL be accepted in the request body.

#### Scenario: Submit backfill-spot job
- **WHEN** `POST /api/v1/housekeeping/backfill-spot` is called with `{"from": "2026-01-01", "to": "2026-03-01", "only_missing": true}`
- **THEN** a job of type `backfill_spot` is created with the provided parameters and HTTP 200 is returned

#### Scenario: Submit validate-warehouse job
- **WHEN** `POST /api/v1/housekeeping/validate-warehouse` is called
- **THEN** a job of type `validate_warehouse` is created and HTTP 200 is returned

---

### Requirement: Script refactoring preserves CLI

Existing CLI scripts (`scripts/backfill_nifty_spot.py`, etc.) SHALL continue to work as standalone CLI tools after refactoring. The core logic SHALL be extracted into importable async functions callable by both the CLI entry point and the job runner.

#### Scenario: CLI still works after refactoring
- **WHEN** `task backfill:spot -- --from 2026-01-01 --only-missing` is run from the terminal
- **THEN** the backfill executes successfully, identical to before the refactor
