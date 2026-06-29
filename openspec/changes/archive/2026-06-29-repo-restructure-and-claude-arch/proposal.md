## Why

PDP has grown into a mature platform (a complete FastAPI backend — 23 REST routers + 6 WS
hubs — and a Flutter app with one proven vertical slice) but the repo is flat: Python,
Flutter, infra and docs all sit at the root, mixed with scratch files, stale logs, and
one-off scripts. This costs two things the owner cares about most:

1. **Claude-development tokens.** Without a clear, scoped structure, every dev session pulls
   in more context than it needs. The repo must be reorganized so each *dev activity* loads
   only the files it requires.
2. **Cloud-readiness.** Local Docker is getting slow; the near-future target is a
   cost-effective AWS deployment via Terraform. Infrastructure-as-code has nowhere to live
   today.

This change is the foundation chunk of a larger program (see the roadmap in the root
`CLAUDE.md`): a **heavy, code-only reorganization** into `backend/ + app/ + infra/ + docs/`,
a **scoped-`CLAUDE.md` system** for token-efficient development, and **thin OpenSpec stubs**
for every downstream chunk so the whole program is browsable.

The package uses src-layout (`src/pdp`, imported as `pdp.*`). Moving it to `backend/pdp`
changes **packaging/config paths only** — no `import pdp.*` statement changes anywhere. The
reorg is mechanical and fully verifiable, not a rewrite.

## What Changes

- **Reorganize (code only, data untouched):** move all Python under `backend/` (flatten
  `src/pdp` → `backend/pdp`; `tests/`, `alembic/`, `backtest/`, `scripts/`, `strategies/`,
  `data/`, `pyproject.toml`, `uv.lock` follow). Move ops/infra under `infra/`
  (`compose/`, `launchers/`, `loadtest/`, `logs/`, reserved `terraform/` + `deploy/`).
  Move `ARCHITECTURE.md`, `RUNBOOK.md`, `docs/*` under `docs/`. `app/` and `openspec/`
  stay put. The MongoDB warehouse and PostgreSQL ledger are external databases — **no data
  migration**.
- **Rework tooling (paths only):** update `pyproject.toml` packaging/ruff/pyright/pytest
  paths, `alembic.ini`, and the root `Taskfile.yml` (per-task `dir:` into `backend/` or
  `infra/`). `app:*` tasks unchanged.
- **Scoped-`CLAUDE.md` system:** slim root `CLAUDE.md` index; `backend/CLAUDE.md` with a
  *dev-activity → minimal-context* table; existing per-module `CLAUDE.md` files travel intact
  with their folders. Each future change folder carries a `README.md` naming its minimal
  context set.
- **Hygiene:** delete `scratch.py`, `scratch2.py`, root `__pycache__/`; clear stale `logs/*`;
  split `scripts/` into `ops/` (recurring, Taskfile-wired) vs `oneoff/` (run-once, absorbing
  the old `scripts/archive/`).
- **Scaffold the roadmap:** thin `proposal.md` + one-line `tasks.md` stubs for chunks 2–16
  under `openspec/changes/`.
- **Realign in-flight changes:** `live-directional-strangle-paper` and
  `backtest-multi-index-strangle` get a program-alignment note and post-reorg
  (`backend/...`) path references. (`order-approval-center` was removed — to be revisited.)

## Capabilities

### New Capabilities
- `repo-architecture`: the canonical repo layout (`backend/ app/ infra/ docs/`), the
  scoped-`CLAUDE.md` development model, the single-Taskfile entrypoint contract, and the
  cloud-readiness constraints (stateless API, decoupled strategy worker, infra-as-code,
  env-only secrets) that later deployment builds on.

## Impact

- **Moves (git mv — history preserved):** `src/pdp`→`backend/pdp`, `tests/`, `alembic/`,
  `backtest/`, `scripts/`, `strategies/`, `data/`, `pyproject.toml`, `uv.lock`,
  `docker-compose.yml`→`infra/compose/`, launchers→`infra/launchers/`, docs→`docs/`.
- **Edits (paths only):** `pyproject.toml`, `Taskfile.yml`, `alembic.ini`, root `CLAUDE.md`,
  `openspec/project.md`, `RUNBOOK.md`, `README.md`.
- **Deletes:** `scratch.py`, `scratch2.py`, root `__pycache__/`, stale `logs/*`.
- **No source-logic edits.** No `import pdp.*` changes. No DB/data migration. No new deps.
- **Safety:** `pre-reorg-baseline` tag + `pre-reorg-backup` branch are the restore point;
  the proven NIFTY strangle backtest is re-run post-move and must match pre-reorg numbers.
- **Out of scope:** the actual Terraform/AWS deploy (chunk 16) and all feature chunks (2–15)
  — only their stubs are created here.
