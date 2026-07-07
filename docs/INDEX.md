# PDP Documentation Index

Quick reference for all project documentation and where to find what you need.

---

## 🎯 By Role / Use Case

### **I'm new — where do I start?**
1. Read [`../CLAUDE.md`](../CLAUDE.md) (5 min) — top-level overview + non-negotiables
2. Read [`RUNBOOK.md` § 1-3](RUNBOOK.md#quick-navigation) (15 min) — setup + quickstart
3. Explore [`backend/CLAUDE.md`](../backend/CLAUDE.md) or [`app/CLAUDE.md`](../app/CLAUDE.md) depending on your focus

### **I'm running the system**
- **How do I start the API?** → [`RUNBOOK.md` § 3-4](RUNBOOK.md#3-starting-the-stack)
- **How do I run the Flutter app?** → [`RUNBOOK.md` § 5](RUNBOOK.md#5-app-flutter-ui)
- **Something broke. What now?** → [`RUNBOOK.md` § 15](RUNBOOK.md#15-common-troubleshooting)
- **What endpoints exist?** → [`RUNBOOK.md` § 4](RUNBOOK.md#4-backend-api-server) (API endpoints table)

### **I'm building a feature**
- **Backend/strategy work?** → [`backend/CLAUDE.md`](../backend/CLAUDE.md) (module map + dev activities)
- **Flutter UI work?** → [`app/CLAUDE.md`](../app/CLAUDE.md) (architecture + patterns)
- **Adding a new strategy?** → [`RUNBOOK.md` § 6](RUNBOOK.md#6-strategy-operations)

### **I'm trading live (directional strangle)**
- **Paper mode setup & operations** → [`RUNBOOK.md` § 17](RUNBOOK.md#17-directional-strangle--paper-mode-operations)
- **Going live for real?** → [`RUNBOOK.md` § 12](RUNBOOK.md#12-live-mode)
- **Monitoring & troubleshooting** → [`RUNBOOK.md` § 7, 14, 15](RUNBOOK.md#7-live-monitor)

### **I'm doing data ops (backfill, migration, DB admin)**
- **Backfill market data** → [`RUNBOOK.md` § 9](RUNBOOK.md#9-data-backfill)
- **Backfill options** → [`RUNBOOK.md` § 10](RUNBOOK.md#10-options-warehouse-gap-backfill)
- **Database admin tasks** → [`RUNBOOK.md` § 13](RUNBOOK.md#13-database-admin)
- **Health checks** → [`RUNBOOK.md` § 14](RUNBOOK.md#14-health-checks)

### **I'm understanding the design**
- **System architecture** → [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Tech stack & conventions** → [`../openspec/project.md`](../openspec/project.md)
- **Project roadmap** → [`~/.claude/projects/.../memory/MEMORY.md`]() (16-chunk program)

---

## 📚 By Document

### Root Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| [`../CLAUDE.md`](../CLAUDE.md) | Top-level index + non-negotiables + workflow | Everyone (start here) |
| [`../openspec/GOVERNANCE.md`](../openspec/GOVERNANCE.md) | 5-phase proposal governance checklist | Proposal authors |
| [`../openspec/project.md`](../openspec/project.md) | Tech stack, conventions, glossary, layout | Architects, leads |

### Operational Documentation

| Document | Purpose | Read When |
|----------|---------|-----------|
| [`RUNBOOK.md`](RUNBOOK.md) | Complete operational reference (setup, run, troubleshoot, data ops) | Starting work, debugging, deploying |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design: three-tier, data flow, DB strategy, deployment | Understanding the design |
| [`ALERTS.md`](ALERTS.md) | Alert engine design: types, evaluation, delivery | Working on alerts |
| [`ALERTS_TESTING.md`](ALERTS_TESTING.md) | Manual steps to test alerts end-to-end | Verifying alert flows |
| [`backtest.md`](backtest.md) | Backtest engine internals: replay, fills, commissions | Debugging backtest results |

### Module Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| `backend/CLAUDE.md` | [`backend/CLAUDE.md`](../backend/CLAUDE.md) | Python module map + dev activities |
| `app/CLAUDE.md` | [`app/CLAUDE.md`](../app/CLAUDE.md) | Flutter architecture + screens |
| `pdp/observability/CLAUDE.md` | `backend/pdp/observability/CLAUDE.md` | OpenSearch pipeline internals |

---

## 🔗 Knowledge Base & Context

### Persistent Memory (Project History & Decisions)

- **Location:** `~/.claude/projects/.../memory/`
- **Index:** `memory/MEMORY.md`
- **What it contains:**
  - Program roadmap (16-chunk breakdown)
  - Executed strategies (SuperTrend, Directional Strangle)
  - Known issues & gaps (indicator warmup, broker friction)
  - Design decisions (MongoDB vs PostgreSQL, Redis for hot cache)
  - User preferences & feedback

**Key memories to reference:**
- `directional_strangle.md` — canonical strangle config, known gaps, lot history
- `live_backtest_parity.md` — 5 live-paper gaps, 18/21 implementation status
- `execution_console_accuracy.md` — indicator divergence (EMA200, RSI, PSAR)
- `backtest_console_priority.md` — backtest as core feature, enterprise standards

---

## 📊 Specifications (OpenSpec)

All feature specifications live in `../openspec/`:

### Archived Capabilities (Source of Truth)
```
openspec/specs/<capability>/
├── spec.md          # Complete design specification
├── proposal.md      # Original proposal + rationale
├── tasks.md         # Implementation checklist (completed)
└── decision_*.md    # Key decisions + alternatives
```

**Key archived specs:**
- `strategy-registry/spec.md` — Unified strategy config schema
- `indicators/spec.md` — 9-family indicator suite
- `backtest-paper-comparison/spec.md` — VS-paper API
- `directional-strangle/spec.md` — Canonical strangle design

### In-Flight Changes
```
openspec/changes/<id>/
├── proposal.md      # Design + scope
├── spec.md          # Implementation spec
├── tasks.md         # Numbered checklist
└── decision_*.md    # Design decisions
```

**Current in-flight:**
- `execution-console-accuracy` — Indicator matrix vs Kite parity
- `live-backtest-parity` — 18/21 complete, 3 deploy-day verifies pending
- `live-directional-strangle-paper` — Rollup, PCR, cam_weekly, parity test

---

## 🛠️ How to Find Things

### "Where is X defined?"
1. Check module `CLAUDE.md` files first (direct paths)
2. Check `RUNBOOK.md` for operational commands
3. Check `openspec/specs/` for capability design
4. Check `memory/MEMORY.md` for decisions + history

### "What's the status of feature Y?"
1. Look in `openspec/changes/` (in-flight) or `openspec/changes/archive/` (done)
2. Check `memory/MEMORY.md` for milestone dates
3. Check `openspec/project.md` for 16-chunk roadmap position

### "Why did we build it that way?"
1. Find the spec in `openspec/specs/<capability>/` or `openspec/changes/archive/`
2. Read `spec.md` (design rationale) + `decision_*.md` (alternatives)
3. Check `memory/` for context on constraints/tradeoffs

---

## 🚀 Quick Commands

All tasks are in `../Taskfile.yml` (single source of truth). Common workflows:

```bash
# Development
task dev              # Start API (:8000)
task test             # Run all tests
task app:run          # Flutter desktop

# Operations
task backtest:strangle -- --days 5    # Quick backtest
task db:up            # Start containers
task search:up        # OpenSearch (:9200 / :5601)

# For complete task list: task -l
```

---

## 📝 Adding Documentation

- **Operational docs** → Add to `docs/` (e.g., `docs/ALERTS_TESTING.md`)
- **Implementation details** → Add to module `CLAUDE.md` (e.g., `backend/pdp/indicators/CLAUDE.md`)
- **Design decisions** → Create spec in `openspec/changes/<id>/decision_*.md`
- **Project history** → Update `memory/MEMORY.md` index + create `memory/<topic>.md`

---

## 🔍 Version & Currency

**Last updated:** 2026-07-07  
**Current chunk:** 6+ (Live trading + Flutter UI + enterprise ops)  
**Canonical strategy:** Directional Strangle (3-index: NIFTY, BANKNIFTY, SENSEX)  
**Status:** 5/5 backtest-console chunks archived; execution-console accuracy in-flight

See [`../CLAUDE.md`](../CLAUDE.md) § Program Roadmap for full status.
