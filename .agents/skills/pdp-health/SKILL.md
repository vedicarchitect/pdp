---
name: pdp:health
description: Run a comprehensive infrastructure health check for the PDP platform — DB connectivity, broker sync status, backfill gaps, Redis/Mongo state, and open strategy status. Use when diagnosing issues, before a live session, or for routine morning checks.
metadata:
  author: pdp
  version: "1.0"
---

Run a PDP infrastructure health check and produce a status report.

## Checks

Run the following checks in parallel where possible. For each: show PASS/WARN/FAIL and details.

### 1. API Health
```
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/strategy/list
```
- PASS: API responds with 200 and at least one strategy listed
- FAIL: Connection refused (API not running) — suggest `task dev`

### 2. Database (PostgreSQL)
```
curl -s http://localhost:8000/api/v1/broker-sync/runs?limit=1
```
Check: response returns 200 (implies DB connectivity). If the API is not running, skip.

Alternatively, read recent migration state:
```
cd backend && uv run alembic current 2>&1
```
- PASS: Shows current revision (should be `0013`)
- WARN: Behind head — suggest `task db:migrate`

### 3. Broker Sync Status
```
curl -s http://localhost:8000/api/v1/broker-sync/runs?limit=5
```
Parse the last run's `status`, `snapshot_date`, and `counts`.
- PASS: Latest run is `ok` and `snapshot_date` is today or yesterday (market was closed)
- WARN: Latest run is `partial` — show which reports failed
- FAIL: No runs today / status `failed` — suggest `task broker:sync`
- INFO: Show counts (holdings, positions, funds, orders, trades, ledger)

### 4. MongoDB Collections
```
curl -s http://localhost:8000/api/v1/broker-sync/holdings?limit=1
```
- PASS: Returns data (implies Mongo is up and `broker_snapshots` is accessible)
- FAIL: Mongo not reachable — suggest `task db:up`

### 5. Strategy Status
```
curl -s http://localhost:8000/api/v1/strategy/list
```
- PASS: `directional_strangle` shows `status: running` (during market hours)
- WARN: Strategy not loaded — suggest `task dev` or check `strategies/` YAML
- INFO: Show `dropped_ticks` count (>0 = hot path lag — investigate)

If chunk 4 is implemented:
```
curl -s http://localhost:8000/api/v1/strangle/status
```
Show: `mode`, `bucket`, `score`, `done_for_day`, `n_open_legs`, `day_pnl`.

### 6. Backfill Gap Check
```
curl -s "http://localhost:8000/api/v1/bars/latest?security_id=13&segment=IDX_I"
curl -s "http://localhost:8000/api/v1/bars/latest?security_id=25&segment=IDX_I"
curl -s "http://localhost:8000/api/v1/bars/latest?security_id=51&segment=IDX_I"
```
For each underlying (NIFTY/BANKNIFTY/SENSEX): show the latest bar timestamp.
- PASS: Latest bar is from today's session (or Friday if weekend)
- WARN: Latest bar is more than 2 trading days old — suggest `task backfill:*`

### 7. Redis (hot cache / pub-sub)
Redis health is implicit in the market feed. If the API is running and strategy is active,
Redis is up. If the API fails to load, check:
```
docker compose -f infra/compose/docker-compose.yml ps
```
Show which containers are `running` vs `exited`.

## Output Format

```
PDP Health Check — <timestamp IST>
=====================================
✅ API             online (strategy: directional_strangle running)
✅ PostgreSQL       migration 0013 (current)
✅ Broker Sync      ok 2026-06-28 | holdings:5 positions:0 funds:1 ledger:2
✅ MongoDB          broker_snapshots accessible
⚠️  Strategy         dropped_ticks: 12 (investigate tick queue lag)
✅ NIFTY bars       latest: 2026-06-28 15:25
✅ BANKNIFTY bars   latest: 2026-06-28 15:25
✅ SENSEX bars      latest: 2026-06-28 15:25
✅ Docker           all 3 containers running
```

End with:
- Overall: ALL GREEN / X WARNINGS / X FAILURES
- Specific remediation commands for any WARN/FAIL
- Suggest `/strangle:review` if the trading session has completed today
