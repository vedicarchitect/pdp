# PDP — Agent Rules & Top-Level Index

Source of truth: `openspec/specs/<cap>/spec.md` · In-flight: `openspec/changes/<id>/`
Full stack/layout: [`openspec/project.md`](openspec/project.md) · **How to run**: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)

## Repository layout (since `repo-restructure-and-claude-arch`)

| Top dir | What | Context entry |
|---------|------|---------------|
| `backend/` | All Python: FastAPI app (`pdp/`), backtests, migrations, scripts, tests | [`backend/CLAUDE.md`](backend/CLAUDE.md) |
| `app/` | Flutter (Dart) trading app — Riverpod + fl_chart | [`app/CLAUDE.md`](app/CLAUDE.md) |
| `infra/` | Ops + infra-as-code: `compose/`, `opensearch/` (dashboards NDJSON), `launchers/`, `loadtest/`, reserved `terraform/`+`deploy/` | — |
| `docs/` | Long-form docs (`ARCHITECTURE.md`, `RUNBOOK.md`, feature docs) | [`docs/CLAUDE.md`](docs/CLAUDE.md) |
| `openspec/` | Specs (source of truth) + in-flight changes | [`openspec/project.md`](openspec/project.md) |

The root `Taskfile.yml` is the single entrypoint — backend tasks run in `backend/`, container
tasks in `infra/compose/`. Market data lives in external DBs (MongoDB warehouse + PostgreSQL
ledger), never in the repo.

## ⛔ Non-Negotiables

1. **Spec-first** — `openspec new change <id>` → implement → `openspec archive <id>`
2. **Paper-first** — live orders only when `LIVE=1` + `BROKER=dhan` + creds. Default = paper.
3. **One mutation/route** — endpoints do one thing.
4. **Universal indicators** — `IndicatorEngine` computes once; strategies consume, never recompute.
5. **Latency** — tick→WS p99 ≤ 50ms. No blocking on hot path.
6. **structlog only** — no `print()` / `rich` in core modules.
7. **Settings via `get_settings()`** — never `os.environ` directly. `.env` lives in `backend/`.
8. **DB split** — PostgreSQL = orders/trades/positions (ACID). MongoDB = bars/chains (time-series). Redis = hot cache/pub-sub.
9. **Speed, quality, clean UI are core — no compromise.** Fast data paths (no N+1, no hot-path blocking); production-grade 60fps UI on live data.
10. **UI is Flutter.** The app lives in `app/`. After UI changes run `cd app && flutter analyze && flutter test`. The old React `frontend/` is removed — do not reference it.
11. **Cloud-ready** — keep the API stateless + env-configured, the strategy worker separately launchable, infra-as-code under `infra/`, secrets in env (→ AWS SSM). See `repo-architecture` spec.

## Token-efficient development — pick your context

Each dev activity loads **only** the files it needs:
- **Backend / Python work** → start at [`backend/CLAUDE.md`](backend/CLAUDE.md) (module map + a
  *dev-activity → minimal-context* table). Per-module `pdp/*/CLAUDE.md` go deeper.
- **App / UI work** → [`app/CLAUDE.md`](app/CLAUDE.md).
- **Working a roadmap chunk** → open `openspec/changes/<id>/README.md` for that chunk's
  minimal context set, then its `proposal.md`.

## Quick Start

**All available tasks** are in [`Taskfile.yml`](Taskfile.yml) at the repo root. Common workflows:

```bash
task dev              # Start backend (uvicorn :8000 --reload)
task test             # Run all tests + lint + typecheck
task backtest:strangle -- --days 5   # Quick 5-day strangle backtest
task app:run          # Flutter desktop app (Windows)
task search:up        # OpenSearch :9200 + Dashboards :5601
```

For a complete list: `task -l` or `grep "^  [a-z]" Taskfile.yml`. Run any task from repo root; Taskfile routing handles directory context.

## Workflow: Spec-First Development

Every feature starts in OpenSpec, then lands in code:

```
1. Propose
   openspec new change my-feature-id
   → Edit: proposal.md (why + scope), spec.md (design), tasks.md (checklist)
   openspec validate --strict my-feature-id

2. Implement
   → Backend: pdp/ modules + tests (pytest green, pyright strict)
   → App: Flutter components (analyze + test green)
   → Integration: backtest vs paper (if strategy-related)

3. Verify
   → For strategies: backtest_multiday.py vs paper_journal (±5% P&L)
   → For UI: manual test in app, screenshot evidence
   openspec verify my-feature-id

4. Archive
   openspec archive my-feature-id
   → Syncs delta specs → openspec/specs/
   → Moves proposal → openspec/changes/archive/YYYY-MM-DD-{id}/
   git commit + git push
```

## Program Roadmap & Status

**Foundation (Chunks 1–5):** ✅ Complete  
**Current (Chunk 6+):** Live trading + Flutter UI + enterprise ops

Full 16-chunk roadmap in [`memory/MEMORY.md`](~/.claude/projects/C--Users-prasa-OneDrive-Desktop-komalavalli-PDP/memory/MEMORY.md).

**Recent milestones:**
- 2026-07-08: Backtest console readability + nav (UX improvements) archived
- 2026-07-04: Flutter backtest console (chunk 8) archived
- 2026-07-05: Flutter dashboard (chunk 6) archived
- 2026-06-26: Directional strangle backtest (+Rs 85.6L, PF 5.72) archived
- **In-flight:** Execution console accuracy (indicator parity), live-backtest-parity (3 deploy-day checks remain)

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| **EMA200 = `--` on app** | Warmup insufficient | See `execution-console-accuracy` memory; increase `_TF_WARMUP_CALENDAR_DAYS` to 180+ days |
| **Backtest faster than paper** | Backtest ignores slippage, rejections, margin | See `live-backtest-parity` memory; add broker friction to paper |
| **RSI/PSAR don't match Kite** | Indicator computation diverges | Verify RSI uses Wilder's EMA; run bar-by-bar comparison for 5 days |
| **Tests fail on Windows** | asyncio teardown race (pre-existing) | Use WSL2 or `pytest -k "not integration"` |
| **LIVE=1 but still paper** | Broker env var not set | Check `BROKER=dhan` + credentials in `backend/.env` |

## OpenSpec Proposal Governance

For infrastructure changes, multi-service refactors, and proposals requiring cross-team validation, follow the 5-phase governance structure (schemas, logic, tests, deployment). See [`openspec/GOVERNANCE.md`](openspec/GOVERNANCE.md) for the full checklist.

## See Also

- **Architecture** → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Operational guide** → [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- **Memory & context** → [`~/.claude/projects/.../memory/MEMORY.md`]() (project history, decisions, knowledge base)
- **Specifications** → [`openspec/specs/`](openspec/specs/) (all archived capabilities)
- **In-flight work** → [`openspec/changes/`](openspec/changes/) (active proposals)