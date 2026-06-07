# Intraday Monitor — Runbooks

## Runbook: Kill-switch fails

**Symptom:** `POST /api/v1/risk/kill` returns `status: "partial"` or `errors` is non-empty.

**Steps:**
1. Check `errors[]` in the response — each item identifies which order/position failed.
2. `sudo journalctl -u pdp --since "5 minutes ago"` — look for `cancel_error` or `place_order_error` structured log entries.
3. If broker rejects cancels: check broker connectivity (`GET /api/v1/health`) and whether the market is open.
4. If positions remain open after the endpoint returns: manually place market-sell orders via broker dashboard.
5. For DHAN broker: check `DHAN_ACCESS_TOKEN` validity (tokens expire after 24h). Regenerate and set in `.env` then restart.
6. Re-call `POST /api/v1/risk/kill` — the endpoint is idempotent (re-cancelling an already-cancelled order is a no-op).

---

## Runbook: WebSocket stuck Disconnected

**Symptom:** Frontend shows red "Disconnected" badge for >30 seconds. Manual page refresh does not fix it.

**Steps:**
1. Check if the backend is running: `curl http://localhost:8000/health`.
2. If backend is down: `systemctl start pdp` (or Docker: `docker-compose up -d`).
3. Check Redis: `redis-cli ping`. If Redis is unreachable, tick subscriptions will fail silently.
4. Check for blocked event loop: look for `portfolio_flush_error` or `portfolio_tick_listener` warnings in logs from the last 5 minutes.
5. If the portfolio WebSocket is specifically stuck: `GET /api/v1/portfolio` (REST fallback) still works — portfolio data is readable without WS.
6. Restart the server (`kill -HUP <pid>` or `systemctl reload pdp`) as a last resort — this resets all WebSocket connections.

---

## Runbook: P&L divergence between frontend and broker

**Symptom:** Portfolio page shows unrealized P&L that differs from broker terminal by >1%.

**Likely causes and fixes:**
1. **LTP stale**: Check `ltp_stale: true` on positions in the portfolio feed. This means the Redis LTP cache expired (>30s without a tick). Cause: no market data for that instrument. Fix: ensure the tick subscription is active (`SUBSCRIBED_SIDS` in logs should include the security_id).
2. **Avg price discrepancy**: The avg price in the PDP `positions` table may differ from the broker if fills arrived out of order. Fix: trigger a position resync via `POST /api/v1/portfolio/sync` (if implemented), or manually update the position row.
3. **Greeks divergence** (for options): Greeks are computed at option chain poll time. If the chain hasn't been polled in the last `OPTIONS_POLL_INTERVAL_SECONDS`, Greeks will be stale. Check `options_poll_completed` log entries.
4. **Currency mismatch**: Ensure broker's P&L is in INR. Futures P&L is point-based (divide by lot size) — this is handled in the backend but verify multipliers in `SecurityMaster`.

---

## Runbook: Hard cap auto-triggered unexpectedly

**Symptom:** Kill-switch executed automatically but loss was within expected bounds.

**Investigation:**
1. Check `hard_cap_breached_auto_kill` log entry: it includes `daily_loss` and `cap` fields. Verify these match expectations.
2. Verify `RISK_DAILY_LOSS_CAP_INR` in `.env` — a misconfigured cap (e.g., `500` instead of `50000`) would trigger early.
3. Check `portfolio_day_start_reset` log entries: the day-start P&L reference should reset at 09:15 IST. If it reset mid-session (server restart), the computed loss may be inflated.
4. If triggered on a server restart: `_hard_cap_triggered` resets on startup. Add startup logic to query yesterday's P&L before enabling the cap (future improvement).

---

## Deployment checklist

Before going live on any trading day:
- [ ] `LIVE=1` in `.env` only if trading real money; `LIVE=0` for paper mode
- [ ] `RISK_DAILY_LOSS_CAP_INR` configured to the correct daily limit
- [ ] `RISK_PER_STRATEGY_LOSS_CAP_INR` set per strategy agreement
- [ ] Broker supports **market orders** (required for kill-switch position flattening)
- [ ] `pnpm test` (backend) and `pnpm exec vitest run` (frontend) both pass
- [ ] `POST /api/v1/risk/kill` tested in paper mode before enabling live trading
- [ ] WebSocket feeds verified live (navigate to `/intraday`, confirm green "Live" badge)
- [ ] Hard cap logic tested: set cap to ₹100, lose ₹101 in paper mode, verify auto-flatten executes
