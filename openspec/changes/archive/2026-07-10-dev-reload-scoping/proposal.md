# dev-reload-scoping

## Why

The 2026-07-09 inflated-P&L incident had a *development-tooling* trigger. A `uvicorn --reload`
process restarted the live paper-trading backend repeatedly, and each restart re-ran
`_rehydrate_legs` — the code path that misclassifies hedge legs as shorts. A SENSEX hedge
(sid 822169) grew 4 → 8 → 16 lots across three uncommanded restarts. The strategy bug is real, but
without the restarts nobody would have hit it three times in one session.

Two distinct defects in the dev tooling:

1. **`--reload` watches too much.** `Taskfile.yml:17` runs `uv run uvicorn pdp.main:app --reload`
   with no `--reload-dir`. Uvicorn defaults to watching the *current working directory* tree. The
   task sets `dir: backend`, so an in-task run watches `backend/` — including `backend/logs/`,
   `backend/data/` and `backend/.venv` churn. Worse, a shell launched from the repo root and running
   `uvicorn` by hand watches the **entire monorepo**: an `openspec archive` write, a `git` checkout,
   or a Flutter edit under `app/` all restart the trading backend. That is what happened.

2. **`task dev` kills the trading backend without asking.** Both `dev` (`Taskfile.yml:16`) and
   `dev:trade` (`:23`) begin with `uv run python scripts/ensure_port_free.py --port 8000`, which
   frees port 8000 by terminating whoever holds it. During a paper session the holder *is*
   `dev:trade`. Running `task dev` in a second terminal — the ordinary thing to do when you want to
   poke at an endpoint — silently kills the strategy host mid-position and hands the port to a
   reloading process. The 2026-07-09 investigation initially blamed a "rogue process"; it was
   `task dev`.

Nothing else can be debugged safely until this lands. Every edit made while diagnosing
`strangle-close-path-atomicity` currently restarts the very system under observation.

## What Changes

- **Scope the watcher.** `task dev` passes `--reload-dir pdp` (relative to `dir: backend`) so only
  importable application code triggers a restart. Logs, data, Mongo dumps, `openspec/`, `docs/`,
  `scratch/` and `app/` cannot.

- **Make `ensure_port_free` refuse to kill a trading process.** The script identifies the process
  holding port 8000 and inspects its command line. If it is a `uvicorn` invocation **without**
  `--reload` (i.e. a `dev:trade` server), the script exits non-zero with a message naming the PID and
  telling the operator to stop it deliberately. A `--force` flag preserves today's behaviour for the
  case where the operator genuinely means it.

- **Refuse `--reload` during market hours.** `task dev` aborts with a clear message when invoked
  between 09:15 and 15:30 IST on a trading day unless `PDP_ALLOW_RELOAD_IN_MARKET=1` is set. The
  reload watcher is a debugging tool; it has no business restarting a strategy that holds positions.

- **Log restarts loudly.** The lifespan logs `app_start` with `started_at` and the value of
  `--reload` as observed from `sys.argv`, so an unexpected restart is greppable rather than inferred
  from a changing `/healthz` timestamp.

## Impact

- **Affected specs:** `dev-reload-scoping` (new).
- **Affected code:** `Taskfile.yml` (`dev`, `dev:trade`), `backend/scripts/ensure_port_free.py`,
  `backend/pdp/main.py` (startup log fields), `docs/RUNBOOK.md`.
- **No production impact.** `dev:trade` — the task used for real paper sessions — gains only a
  refusal-to-kill guard and a startup log field. No runtime behaviour on the hot path changes.
- **Blocks everything else.** Land this before `strangle-close-path-atomicity` and
  `strangle-leg-state-durability`: those are debugged by editing strategy code while a session runs,
  which today re-triggers the exact bug being investigated. Ties into
  [[task_dev_reload_conflict]] and [[leg_rehydration_misclassification_bug]].
