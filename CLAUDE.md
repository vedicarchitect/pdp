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

## Program roadmap (chunks = OpenSpec changes)

Foundation **1** `repo-restructure-and-claude-arch` (✓ done). Then:
**2** `broker-account-sync` (✓ done) · **3** `broker-reports-vault` · **4** `strangle-execution-console` (42/43 — owner paper-run pending) ·
**5** `trade-analysis-feedback-loop` (✓ done — unified OpenSearch log pipeline, archived 2026-06-28) · **6** `flutter-dashboard` · **7** `flutter-screener` ·
**8** `flutter-backtest-console` (✓ done, archived 2026-07-04 — see Backtest console program below) · **9** `flutter-risk-positions` · **10** `flutter-journal` ·
**11** `flutter-portfolio-advisory` · **12** `flutter-market-intel` · **13** `flutter-event-feed` ·
**14** `flutter-management-hub` · **15** `multi-broker-kite` · **16** `cloud-deploy-aws`.
In-flight strangle work: `live-directional-strangle-paper`. `backtest-multi-index-strangle` ✓ done — BANKNIFTY +₹35.1L PF 4.89, SENSEX +₹24.7L PF 6.21 (3yr), archived 2026-06-29.

### Backtest console program (5 changes, backend-first) — ✓ all done

Made the backtest console enterprise-grade + DB-first (no local result files). Order:
**1** `backtest-results-warehouse` (✓ done, archived 2026-07-04 — real sweeps+leaderboard, strategy-agnostic
decision-trace, promotion evidence snapshot, DB-first cutover, legacy runs ingested) · **2** `market-data-coverage`
(✓ done, archived 2026-07-04 — per-index/family coverage API, gap radar, delta-fill jobs, multi-index self-heal, OpenSearch dashboard) ·
**3** `backtest-paper-comparison` (✓ done, archived 2026-07-04 — per-strategy paper P&L from the PG ledger,
`GET /runs/{id}/vs-paper` day+minute alignment, gap-radar divergence root-causing, ST-only `compare.py` retired) ·
**4** `strategy-registry-unification` (✓ done, archived 2026-07-04 — canonical-id registry spanning live
`strategies/*.yaml` + backtest `backtest/configs/*.yaml`, `GET /api/v1/strategies` with editable param
schema, `POST /register`, `canonical_id()` wired into run identity + vs-paper; `/strategy:add` skill) ·
**5** `flutter-backtest-console` (✓ done, archived 2026-07-04 — Flutter console rebuilt to house
convention: run history/leaderboard, run-detail drill-downs incl. decision trace + walk-forward folds,
schema-driven launch flow, coverage/gap-radar panel, promotion rationale, backtest-vs-paper view,
CSV/JSON export, OpenSearch dashboard links; `flutter analyze && flutter test` green). See
`openspec/changes/archive/2026-07-04-<id>/` for each.

## Key Commands (run from repo root)

```bash
task dev          # uvicorn :8000 --reload   (runs in backend/)
task db:up / db:migrate / db:down / db:tools  # compose in infra/compose/
task test / lint / fmt / typecheck            # ruff/pytest/pyright in backend/
task backtest:strangle -- --days 90           # directional-strangle backtest
task backfill:nifty -- --from YYYY-MM-DD [--only-missing]   # + :banknifty / :sensex / :options
task app:run / app:live / app:test            # Flutter (Windows desktop)
task search:up / search:init                  # OpenSearch + Dashboards (:9200 / :5601)
task openspec:list / openspec:validate -- <id> / openspec:archive -- <id>
```
