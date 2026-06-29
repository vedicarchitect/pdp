# repo-architecture Specification

## Purpose
Repository layout, packaging, and cloud-readiness constraints: four top-level directories, behavior-preserving reorganization, single Taskfile entrypoint, scoped CLAUDE.md development model, and cloud-deployment readiness.

## Requirements

### Requirement: Top-level repository split
The repository SHALL be organized into four top-level code/ops directories — `backend/`
(all Python), `app/` (Flutter), `infra/` (ops + infra-as-code), and `docs/` (long-form
docs) — alongside `openspec/`. Market data SHALL NOT be relocated by this structure: the
MongoDB warehouse and PostgreSQL ledger are external databases.

#### Scenario: Python lives under backend/
- **WHEN** a contributor looks for the FastAPI app, strategies, backtests, or migrations
- **THEN** they find them under `backend/` (`backend/pdp`, `backend/backtest`,
  `backend/alembic`, `backend/scripts`) with the package still importable as `pdp.*`

#### Scenario: Infra-as-code has a home
- **WHEN** deployment or local-stack files are needed
- **THEN** they live under `infra/` (`infra/compose`, `infra/launchers`, `infra/loadtest`)
  with `infra/terraform/` and `infra/deploy/` reserved for cloud deployment

### Requirement: Behavior-preserving move
The reorganization SHALL change packaging and configuration paths only and MUST NOT alter
any `import pdp.*` statement, strategy/backtest logic, or database data. The proven NIFTY
strangle backtest MUST produce identical results (trade count, Net, PF, MaxDD) before and
after the move.

#### Scenario: Tests and strategy parity pass post-move
- **WHEN** the move is complete and `uv sync` has run under `backend/`
- **THEN** the full pytest suite passes and the NIFTY strangle backtest matches its
  pre-reorg baseline within floating-point tolerance

#### Scenario: History is preserved
- **WHEN** `git log --follow` is run on a moved file (e.g. `backend/pdp/main.py`)
- **THEN** its full pre-move history is shown, and `pre-reorg-baseline` / `pre-reorg-backup`
  remain as the restore point

### Requirement: Single Taskfile entrypoint
The root `Taskfile.yml` SHALL remain the single command entrypoint after the move, delegating
into `backend/` and `infra/` via per-task working directories. Existing task names SHALL keep
working.

#### Scenario: Common tasks work unchanged
- **WHEN** a contributor runs `task dev`, `task test`, `task lint`, or `task app:run`
- **THEN** each runs correctly from the new layout without the caller changing directories

### Requirement: Scoped CLAUDE.md development model
The repository SHALL provide tiered, scoped `CLAUDE.md` context so each development activity
loads only the files it needs: a slim root index, a `backend/CLAUDE.md` with a
dev-activity → minimal-context table, per-module `CLAUDE.md` files, and a `README.md` naming
the minimal context set in each change folder.

#### Scenario: A dev activity has a bounded context set
- **WHEN** a contributor (human or Claude) begins work on a known activity (e.g. the strangle)
- **THEN** the relevant `CLAUDE.md` names the specific files to load and excludes the rest

### Requirement: Cloud-readiness constraints
The architecture SHALL preserve cloud-deployment readiness so a later Terraform/AWS chunk
needs no further reorganization: the API SHALL remain stateless and env-configured, the
strategy worker SHALL remain a separately-launchable process decoupled from the API, all
infra-as-code SHALL live under `infra/`, and secrets SHALL be sourced from the environment
(never committed) so they map to AWS SSM / Secrets Manager.

#### Scenario: Deployment slots in without reorg
- **WHEN** the cloud-deploy chunk begins
- **THEN** it adds Terraform/Dockerfiles under the reserved `infra/terraform` and
  `infra/deploy` without moving application code or changing import paths
