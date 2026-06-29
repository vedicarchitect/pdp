## Context

The repo is flat: Python (`src/pdp`, `tests`, `alembic`, `backtest`, `scripts`,
`strategies`, `data`), Flutter (`app`), infra (`docker-compose.yml`, launchers, `loadtest`),
and docs (`ARCHITECTURE.md`, `RUNBOOK.md`, `docs/`) all share the root with scratch files and
stale logs. The owner wants a heavy reorg into `backend/ app/ infra/ docs/` that is (a)
token-efficient for Claude development and (b) cloud-ready, **without** changing behavior.

## Goals / Non-Goals

**Goals:**
- One coherent top-level split: `backend/ app/ infra/ docs/ openspec/`.
- Token-efficient development: each dev activity has a scoped `CLAUDE.md` / minimal context set.
- Reserve infra-as-code homes so AWS/Terraform (chunk 16) slots in with no further reorg.
- Provably zero behavior change (full test suite + NIFTY strangle parity).

**Non-Goals:**
- Any data/DB migration (warehouse + ledger are external).
- Any `import pdp.*` or strategy/backtest logic edits.
- The actual cloud deployment (chunk 16) or any feature chunk (2–15).

## Key decision — src-layout makes this mechanical

The Python package is `pdp` under `src/` (src-layout), imported everywhere as `pdp.*`. The
import name is independent of the directory that holds the package, as long as packaging
points at the new location and the env is re-synced. Therefore moving `src/pdp` →
`backend/pdp` (flattening away `src/`) requires **only** packaging/config path edits:

- `pyproject.toml` (now at `backend/`): `[tool.hatch.build.targets.wheel] packages = ["pdp"]`,
  `[tool.ruff] src = ["pdp","tests"]`, `[tool.pyright] include = ["pdp"]`, pytest
  `testpaths = ["tests"]` — all relative to `backend/`.
- `alembic.ini` (now at `backend/`): `script_location = alembic`, `prepend_sys_path = .` unchanged.

No `.py` file under `pdp/`, `tests/`, `backtest/`, or `scripts/` changes its imports.

## Decisions

### D1: `backend/` holds all Python; `uv` runs from there
The root `Taskfile.yml` stays the single entrypoint; backend tasks gain `dir: backend`, infra
tasks `dir: infra`. `uv` resolves the project from `backend/pyproject.toml`; the `.venv` lives
in `backend/`. `app:*` tasks are unchanged.

### D2: `infra/` reserves cloud homes now
`infra/{compose,launchers,loadtest,logs}` exist immediately; empty `infra/terraform/` and
`infra/deploy/` are reserved so chunk 16 lands without another reorg. Cloud-readiness
constraints are recorded as requirements: stateless env-config API, separately-launchable
strategy worker, infra-as-code under `infra/`, secrets in env (→ AWS SSM/Secrets Manager).

### D3: Scoped-`CLAUDE.md` development model
- Root `CLAUDE.md`: slim index → `backend/ app/ infra/ docs/`, the chunk roadmap, and a
  "how to pick context for a dev activity" pointer.
- `backend/CLAUDE.md`: module map + a **dev-activity → minimal-context** table (e.g. "strangle
  work → `pdp/strategies/strangle*`, `pdp/signals/`, `backtest/strangle_run.py`; nothing else").
- Existing per-folder `CLAUDE.md` files move intact with their modules.
- Each future change folder carries a `README.md` naming its minimal context set.

### D4: Scripts split ops vs one-off
`backend/scripts/ops/` = recurring, Taskfile-wired (backfill/audit/validate);
`backend/scripts/oneoff/` = run-once + the absorbed `scripts/archive/`. Taskfile paths point
at `ops/`.

## Risks / Trade-offs

- **Running backfills (BANKNIFTY/SENSEX in progress):** moving files doesn't disturb a
  running process (open file handle), but new `task backfill:*` calls resolve to
  `backend/scripts/ops/`. Mitigation: move during a gap between batches; run one
  `--dry-run` before resuming.
- **`uv` env relocation:** the `.venv` must be re-created under `backend/` (`uv sync`).
  Mitigation: part of the verification checklist.
- **Wide path churn in tooling:** mitigated by the src-layout invariant — only config files,
  not source, change.

## Migration Plan

1. `git tag pre-reorg-baseline` + `git branch pre-reorg-backup` (done).
2. Capture a pre-reorg NIFTY strangle backtest result for parity comparison.
3. `git mv` moves (backend / infra / docs).
4. Edit `pyproject.toml`, `alembic.ini`, `Taskfile.yml` paths.
5. Author the scoped `CLAUDE.md` system + update `openspec/project.md`, `RUNBOOK.md`, `README.md`.
6. Hygiene deletes + scripts split.
7. Scaffold chunk 2–16 stubs; realign the two in-flight strangle changes.
8. Verify (uv sync, test, lint, typecheck, migrate, dev boot, flutter analyze, openspec list,
   git history, strategy parity). Rollback = `git reset --hard pre-reorg-baseline`.

## Open Questions
- None blocking. Whether `data/` ultimately belongs under `backend/` or `infra/` is settled
  as `backend/data/` (scripts read it); revisit only if cloud storage supersedes it in chunk 16.
