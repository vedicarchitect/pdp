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
10. **UI is Flutter.** The app lives in `app/`. After UI changes run `cd app && flutter analyze --fatal-infos && flutter test` (or `task app:test`). The old React `frontend/` is removed — do not reference it.
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
- 2026-07-25: `bias-ranking-hardening` (quorum floor + extreme-bucket guard + backtest warmup prefix,
  archived 2026-07-22) and `strangle-orphan-fill-reconciliation` (archived 2026-07-25) both landed on
  branch `startegy`, **not yet committed**. The latter's live `dev:trade` smoke test surfaced 2 more
  root causes beyond its original scope (stale OPEN orders re-arming on boot, a portfolio flush/reload
  race clobbering just-flattened P&L) plus a live cleanup (3 orphan positions, 35 stale orders, 119
  historical P&L-display rows). A same-day `/code-review max --fix` pass on the combined diff (which
  also includes the still-in-progress `bias-ranking-multisignal` ST/PSAR/ATM-vote work) found and
  fixed 4 more real bugs — most notably that `_open_hedge`/`_open_momentum` never got the
  cancel-confirmation fix `_open_short` did, leaving the same orphan-fill race open in 2 of 3 entry
  paths — and flagged (without auto-fixing) that the live NIFTY/BANKNIFTY/SENSEX strategy YAMLs carry
  `bias-ranking-multisignal` placeholder weights its own `tasks.md` says not to promote. `task test`:
  1219 passed, 0 failed. See `memory/strangle_orphan_fill_reconciliation.md`,
  `memory/bias_ranking_multisignal.md`, `memory/code_review_2026_07_25_findings.md`.
- 2026-07-17: Go-live hardening pass on live-session evidence (root cause: entry-path fill race +
  one-shot bucket latch silently blocked NIFTY/BANKNIFTY paper entries) — fixed and pushed to
  `papermode`: `strangle-partial-entry-recovery` (bounded per-side recovery, 2 correctness gaps from
  `/code-review` also fixed: `naked_hedge_averted` latch + day-rollover pin), plus
  `indicator-matrix-kite-parity` (**archived**), `strangle-entry-fill-race-and-latch`,
  `indicator-warmup-derive-from-1m`, `strangle-readiness-indicators-truthful`,
  `execution-panel-freshness-and-events`, and a new `strangle-monitor-concurrent-fetch`
  (`/monitor`'s 4 sequential I/O chains → `asyncio.gather`). `task test`: 1203 passed, 0 failed.
  All 6 non-archived changes above are implementation-complete; only their live/boot-smoke tasks and
  `openspec archive` remain, gated on the next market day.
- 2026-07-13: Incident-remediation program **complete** — all 10 `EXECUTION-ORDER.md` changes plus
  `flutter-execution-tab-layout` and `lot-size-live-reconciliation` archived (`bar-session-anchoring`,
  `indicator-history-depth`, `bias-input-completeness`, `strangle-close-path-atomicity`,
  `strangle-leg-state-durability`, `strangle-observability-gaps`, `dhan-same-day-data`,
  `market-bars-duplicate-write-fix`). Combined re-baseline verdict: **supersede** the archived NIFTY
  backtest — new baselines are NIFTY +Rs 42.71L, BANKNIFTY +Rs 46.82L, SENSEX +Rs 20.87L (full trace
  in each change's archived README). A genuine `option_bars` expiry-cadence data gap was found and
  disentangled from the fixes' own effect; filed separately as `option-bars-expiry-gap-backfill`
  (in-flight, blocked on live Dhan creds). `task test`: 1131 passed, 0 failed.
- 2026-07-10: `test-suite-baseline-green` archived — backend suite genuinely green (1010 passed,
  2 intentional `xfail(strict=True)`), Flutter `flutter analyze --fatal-infos` zero issues, CI added
  (`.github/workflows/ci.yml`); unblocked `bar-session-anchoring`
- 2026-07-10: `dev-reload-scoping` archived — `task dev` scoped to `backend/pdp`, refuses to kill a
  live `dev:trade`, refuses during market hours; unblocked the incident-remediation program
- 2026-07-09: Live-trading incident (dev-tooling-triggered leg-growth bug) → 10 remediation
  OpenSpec changes authored, execution order in `openspec/changes/EXECUTION-ORDER.md`
- 2026-07-08: Backtest console readability + nav (UX improvements) archived
- 2026-07-04: Flutter backtest console (chunk 8) archived
- 2026-07-05: Flutter dashboard (chunk 6) archived
- 2026-06-26: Directional strangle backtest (+Rs 85.6L, PF 5.72) archived — **superseded 2026-07-13**,
  see above
- **In-flight:** `option-bars-expiry-gap-backfill` (data-completeness follow-up, blocked on live Dhan
  creds); `strangle-partial-entry-recovery`, `strangle-entry-fill-race-and-latch`,
  `indicator-warmup-derive-from-1m`, `strangle-readiness-indicators-truthful`,
  `execution-panel-freshness-and-events`, `strangle-monitor-concurrent-fetch` (all code-complete,
  each blocked only on a live/boot smoke check + `openspec archive`). Two earlier live-paper-session
  deploy-day checks also remain open (recorded in the archived
  `strangle-close-path-atomicity`/`strangle-leg-state-durability` tasks) — all of the above need a
  `dev:trade` session during market hours, not code.

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| **A period (e.g. EMA200) = `--` on app** | Genuinely unconverged — see `indicator-history-depth` | Check the `indicator_seeding_summary` startup log line for that strategy; if the period isn't listed as configured, add it to the watchlist's `indicators:`; if configured but unseeded, `market_bars` doesn't yet hold `required_bars()` bars for that `(sid, tf)` — run `scripts/backfill_market_bars.py` |
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