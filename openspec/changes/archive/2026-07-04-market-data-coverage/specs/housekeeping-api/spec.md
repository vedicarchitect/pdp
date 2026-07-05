## MODIFIED Requirements

### Requirement: Housekeeping REST API
The system SHALL expose `POST /api/v1/housekeeping/{task}` for tasks: `backfill-spot`,
`backfill-options`, `backfill-levels`, `backfill-vix`, `reset-paper`, `snapshot-instruments`,
`validate-warehouse`. Each endpoint SHALL submit the task as an async job via the job runner and
return the job record. Task-specific parameters SHALL be accepted in the request body, including a
`symbol` (NIFTY | BANKNIFTY | SENSEX) for the backfill tasks so a delta-fill can target any index;
when `symbol` is omitted it SHALL default to NIFTY for backward compatibility.

#### Scenario: Submit backfill-spot job
- **WHEN** `POST /api/v1/housekeeping/backfill-spot` is called with `{"from": "2026-01-01", "to": "2026-03-01", "only_missing": true}`
- **THEN** a job of type `backfill_spot` is created with the provided parameters and HTTP 200 is returned

#### Scenario: Submit a symbol-scoped backfill job
- **WHEN** `POST /api/v1/housekeeping/backfill-options` is called with `{"symbol": "BANKNIFTY", "from": "2026-06-01", "only_missing": true}`
- **THEN** a job is created that backfills BANKNIFTY options (sid 25, step 100) for the delta window and HTTP 200 is returned

#### Scenario: Submit validate-warehouse job
- **WHEN** `POST /api/v1/housekeeping/validate-warehouse` is called
- **THEN** a job of type `validate_warehouse` is created and HTTP 200 is returned

### Requirement: Script refactoring preserves CLI
Existing CLI scripts (`scripts/backfill_spot.py`, etc.) SHALL continue to work as standalone CLI
tools. Housekeeping job handlers (`pdp/housekeeping/tasks.py`) SHALL invoke these scripts as
subprocesses (`asyncio.create_subprocess_exec`) rather than importing shared async functions —
this is the established pattern for every housekeeping task (not something reworked by this
change; the requirement name is retained from the prior change that introduced it, even though
"refactoring into importable async functions" never actually happened — the subprocess approach
was the real, working design). The job handlers SHALL pass the `symbol` parameter through as a
`--symbol` CLI arg so symbol-scoped jobs run the exact same code path as the CLI.

#### Scenario: CLI still works standalone
- **WHEN** `task backfill:nifty -- --from 2026-01-01 --only-missing` is run from the terminal
- **THEN** the backfill executes successfully, independent of the job-runner subprocess path

#### Scenario: Symbol flows from job to CLI args
- **WHEN** a `backfill-options` job is submitted with `symbol=SENSEX`
- **THEN** the handler invokes the backfill subprocess with `--symbol SENSEX`, producing docs with `underlying=SENSEX`
