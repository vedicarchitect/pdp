# dev-reload-scoping — minimal context

Read only these to work this change.

| File | Why |
|------|-----|
| `Taskfile.yml` | `dev:12-17`, `dev:trade:19-24` — the two tasks that change |
| `backend/scripts/ensure_port_free.py` | Kills the port-8000 holder unconditionally today |
| `backend/pdp/main.py` | Lifespan; add the `app_start` attribution log |
| `docs/RUNBOOK.md` | Operator instructions for paper-session startup |

## Key facts established during investigation
- `task dev` and `task dev:trade` **both** call `ensure_port_free.py --port 8000` first, so the
  second one launched wins — silently killing an in-session strategy host.
- `uvicorn --reload` with no `--reload-dir` watches the CWD tree. Launched from the repo root by
  hand it watches the whole monorepo, so `openspec archive` writes restart the trading backend.
- Each restart re-runs `_rehydrate_legs`, which is the misclassification bug — restarts are the
  amplifier, not the root cause.

## Related
Blocks `strangle-close-path-atomicity` and `strangle-leg-state-durability`: both are diagnosed by
editing strategy code during a live session, which today restarts the system under observation.
