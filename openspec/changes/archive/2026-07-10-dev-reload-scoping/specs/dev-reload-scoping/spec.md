## ADDED Requirements

### Requirement: The development reload watcher SHALL observe only application source

The `dev` task SHALL pass an explicit `--reload-dir` limited to the importable application package,
so that writes to logs, local data, `openspec/`, `docs/`, `scratch/`, `app/` and version-control
metadata do not restart the backend.

#### Scenario: A spec file is written while the backend runs

- **WHEN** a file under `openspec/` or `docs/` is created or modified
- **THEN** the reloading backend does not restart

#### Scenario: Application source is edited

- **WHEN** a file under `backend/pdp/` is modified
- **THEN** the reloading backend restarts

#### Scenario: Log rotation does not restart the app

- **WHEN** the strategy writes to `backend/logs/` during a session
- **THEN** the reloading backend does not restart

### Requirement: Port reclamation SHALL NOT terminate a non-reloading trading server

`ensure_port_free.py` SHALL inspect the command line of the process holding the target port. When
that process is a `uvicorn` server started without `--reload`, the script SHALL exit non-zero
without terminating it, naming the PID and the command line in its message. An explicit `--force`
flag SHALL restore unconditional termination.

#### Scenario: A trading server holds the port

- **WHEN** `task dev` is run while `dev:trade` owns port 8000
- **THEN** `ensure_port_free.py` exits non-zero, the trading server keeps running, and the message names its PID

#### Scenario: A stale reload server holds the port

- **WHEN** `task dev` is run while an abandoned `uvicorn --reload` owns port 8000
- **THEN** that process is terminated and the port is freed

#### Scenario: Operator forces reclamation

- **WHEN** `ensure_port_free.py --force` is run while a trading server owns the port
- **THEN** the process is terminated

#### Scenario: Port is already free

- **WHEN** no process holds the target port
- **THEN** the script exits zero without inspecting any process

### Requirement: The reload watcher SHALL refuse to start during market hours

The `dev` task SHALL abort when invoked between 09:15 and 15:30 IST on a trading day, unless the
environment variable `PDP_ALLOW_RELOAD_IN_MARKET` is set to `1`. The message SHALL direct the
operator to `task dev:trade`.

#### Scenario: Reload attempted mid-session

- **WHEN** `task dev` is invoked at 11:00 IST on a trading day without the override
- **THEN** the task exits non-zero, no server starts, and the message names `task dev:trade`

#### Scenario: Reload attempted outside market hours

- **WHEN** `task dev` is invoked at 20:00 IST
- **THEN** the reloading server starts normally

#### Scenario: Operator overrides deliberately

- **WHEN** `PDP_ALLOW_RELOAD_IN_MARKET=1 task dev` is invoked at 11:00 IST
- **THEN** the reloading server starts and logs a warning that reload is active during market hours

### Requirement: Startup SHALL record whether the reload watcher is active

The application lifespan SHALL log an `app_start` event carrying `started_at` and a boolean
indicating whether the process was launched with `--reload`, so that an unexplained restart is
attributable from logs alone.

#### Scenario: Restart is attributable

- **WHEN** the backend restarts unexpectedly during a session
- **THEN** the log contains an `app_start` event with a fresh `started_at` and the reload flag, without needing to poll `/healthz`
