## Why

PDP needs three layers of autonomous Claude-assisted operations: (1) post-session trade
review that analyzes the structured strangle logs and surfaces insights without manual
intervention, (2) infrastructure health monitoring that catches broker sync failures,
backfill gaps, and DB issues proactively, and (3) scheduled agents that run on a clock
(pre-market warmup check, EOD log analysis, weekly performance digest). The slash-command
skills (`/strangle:review`, `/pdp:health`, `/pdp:insights`) are manual; this chunk adds the
automated / scheduled counterparts and backend API endpoints that feed them.

> **Stub** — part of the PDP program roadmap. Implement after `strangle-execution-console`
> (chunk 4) since the canonical log schema that feeds these agents is built there.
> Skills are already created in `.claude/skills/`; this change adds the backend APIs and
> scheduled agent infrastructure.

## What Changes

- **Backend log-export API**: `GET /api/v1/strangle/log?date=YYYY-MM-DD` serves the daily
  structured log file as JSON lines so Claude agents can read it without filesystem access.
- **Health-check API** (`GET /api/v1/health/detail`): structured JSON covering DB, Mongo,
  broker sync, strategy status, backfill freshness — machine-readable for agent consumption.
- **Scheduled agent hooks**: Claude Code `CronCreate` invocations for:
  - Pre-market (9:00 IST weekdays): warmup check + data freshness alert
  - EOD (15:45 IST weekdays): auto-trigger `/strangle:review` for today
  - Weekly (Saturday 10:00 IST): auto-trigger `/pdp:insights` for the week
- **Notification hooks** in `settings.local.json`: emit PushNotification on broker sync
  failure, recon mismatch, or dropped_ticks spike.
- **Broker recon agent**: a standalone agent prompt that reads the last 5 broker sync runs,
  checks recon mismatches vs internal positions, and flags any drift — runnable on demand
  via `/pdp:recon`.

## Capabilities

### New Capabilities
- `claude-ops-agents`: log-export API, health-detail API, scheduled agents (pre-market /
  EOD / weekly), notification hooks, recon agent skill.

### Modified Capabilities
_(none)_

## Impact

- **`backend/pdp/strategy/routes.py`**: `GET /api/v1/strangle/log`
- **`backend/pdp/main.py`**: `GET /api/v1/health/detail`
- **`.claude/settings.local.json`**: notification hooks
- **`.claude/skills/pdp-recon/SKILL.md`**: new `/pdp:recon` skill
- **Scheduled agents**: created via `CronCreate` (Claude Code cloud agents)
- **Depends on**: `strangle-execution-console` (chunk 4) for canonical log schema
