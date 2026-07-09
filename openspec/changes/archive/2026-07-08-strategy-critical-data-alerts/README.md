# strategy-critical-data-alerts

**Minimal context set** (load only these when working this change):
- `proposal.md`, `design.md` (GOVERNANCE 5-phase), `tasks.md`, `specs/strategy-critical-data-alerts/spec.md`
- Backend: `backend/pdp/events/` (`models.py`, `service.py`, `CLAUDE.md`), `strategy/context.py`,
  `strategy/host.py`, `strategies/directional_strangle.py`, `indicators/warmup.py`,
  `market/router.py` + feed watchdog
- Flutter: `app/lib/features/events/`
- Findings behind this change: C5 (naked hedge), C9 (unseeded ORB), C13 (VIX ticks) + warmup/feed
  from the approved plan.

**Ship order:** parallel with change #1 (`api-reliability-hardening`), which un-swallows the
money/data failures this change surfaces. Complements change #3's non-blocking warmup.
