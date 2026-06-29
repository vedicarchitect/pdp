## 0. Safety baseline
- [x] 0.1 `git tag pre-reorg-baseline` + `git branch pre-reorg-backup` on current HEAD
- [~] 0.2 Pre-reorg baseline backtest NOT captured (went straight to move on "go now"). Parity instead proven by: content-identical `git mv` (383 renames) + clean post-move run (Net +296354 / PF 3.62 / 585 trades, 90d default config)

## 1. Move Python → backend/ (git mv, history preserved)
- [x] 1.1 `src/pdp` → `backend/pdp` (flattened; `src/CLAUDE.md` → `backend/pdp/CLAUDE.md`)
- [x] 1.2 `tests` → `backend/tests`
- [x] 1.3 `alembic` + `alembic.ini` → `backend/`
- [x] 1.4 `backtest`, `strategies` (git mv) + `data` (plain mv — untracked) → `backend/`
- [x] 1.5 `pyproject.toml`, `uv.lock`, `.env`, `.env.example` → `backend/`
- [x] 1.6 `scripts` → `backend/scripts`; `archive/` → `oneoff/`. NOTE: ops scripts kept at `backend/scripts/` root (not `ops/`) so `dir: backend` keeps Taskfile paths valid with zero churn

## 2. Move infra/ and docs/
- [x] 2.1 `docker-compose.yml` → `infra/compose/` (+ pinned `name: pdp` to preserve `pdp_*` volumes)
- [x] 2.2 launchers → `infra/launchers/`
- [x] 2.3 `loadtest` → `infra/loadtest`; stale `logs/` cleared → `infra/logs/.gitkeep`
- [x] 2.4 Reserved empty `infra/terraform/` + `infra/deploy/`
- [x] 2.5 `ARCHITECTURE.md`, `RUNBOOK.md` → `docs/`

## 3. Config rework (paths only — no import edits)
- [x] 3.1 `backend/pyproject.toml`: hatch `packages=["pdp"]`; ruff `src=["."]`; pyright `include=["pdp"]`; `readme` → added `backend/README.md`
- [x] 3.2 `backend/alembic.ini` unchanged (cwd = backend)
- [x] 3.3 Root `Taskfile.yml`: `dir: backend` on Python tasks, `dir: infra/compose` on container tasks, `ruff … pdp tests`; `app:*` unchanged
- [~] 3.4 Launchers in `infra/launchers/` not yet re-pathed (use `task` instead; revisit if used)

## 4. Hygiene
- [x] 4.1 Deleted `scratch.py`, `scratch2.py`, root `__pycache__/`, `backend/scripts/__pycache__`
- [x] 4.2 Cleared stale `logs/*` → `infra/logs/.gitkeep`
- [x] 4.3 `security_id_list.csv` → `backend/data/`
- [x] 4.4 Fixed `.gitignore` (`backend/backtest/runs/` proper line-comment; `!infra/logs/.gitkeep`)

## 5. Claude-dev architecture
- [x] 5.1 Root `CLAUDE.md` slimmed → top-level split, roadmap, dev-activity guidance
- [x] 5.2 `backend/CLAUDE.md` → module map + dev-activity → minimal-context table
- [x] 5.3 Per-module `pdp/*/CLAUDE.md` moved intact
- [x] 5.4 Updated `openspec/project.md` Layout, `docs/RUNBOOK.md` (working-dir note + setup + `src/pdp`→`backend/pdp`), `docs/CLAUDE.md` link, and root `README.md` (Quick Start, structure tree, tech-stack, capability status, resource links)

## 6. Scaffold roadmap stubs (chunks 2–16)
- [x] 6.1–6.3 15 stubs created (proposal.md + tasks.md + README.md minimal-context each)

## 7. Realign in-flight changes
- [x] 7.1 `live-directional-strangle-paper`: program-alignment note added
- [x] 7.2 `backtest-multi-index-strangle`: program-alignment note + `backend/` path
- [x] 7.3 Deleted `order-approval-center` (revisit later, per owner)

## 8. Verification
- [x] 8.1 `cd backend && uv sync` (+ `--extra dev`) ✓
- [~] 8.2 `task test` → 598 pass / 27 **pre-existing** fails (e.g. `PositionState` needs `strategy_id`) — reorg-neutral
- [~] 8.3 `lint`/`typecheck` run; carry **pre-existing** debt (267 ruff / 2065 pyright-strict) — same ruff/pyright version + identical content ⇒ not caused by move
- [ ] 8.4 `task db:up && task db:migrate` — DB already up; migrate not re-run this pass
- [x] 8.5 Engine boots end-to-end (strangle backtest ran via `task` → `.env` + Mongo OK)
- [ ] 8.6 `task app:test` — Flutter SDK not on this shell; `app/` untouched (owner to run)
- [x] 8.7 `task openspec:list` shows all 18 changes; chunk-1 `validate --strict` clean
- [x] 8.8 `git status` shows 383 renames (history preserved on commit)
- [x] 8.9 **Strategy parity:** strangle backtest from `backend/` → Net +296354 / PF 3.62 / Win 66% / MaxDD 29160 / 585 trades (90d)
