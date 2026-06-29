# strangle-live-paper-hardening

Fixes the five defects surfaced by `/strangle-review` on the 2026-06-29 three-index paper session.

**Minimal context set** (load only these when working this chunk):
- backend/pdp/strategy/host.py, backend/pdp/strategy/context.py        (R1 — LTP delivery)
- backend/pdp/orders/paper.py                                          (R2 — fill integrity)
- backend/pdp/strategies/directional_strangle.py                       (R2/R3/R4/R5)
- backend/pdp/signals/bias.py, backend/pdp/indicators/warmup.py        (R3 — signals)
- backend/pdp/options/ (chain poller, for PCR)                         (R3 — pcr)
- backend/strategies/directional_strangle_*.yaml                       (R3/R4 config)
- reference: `/strangle-review` 2026-06-29 logs under backend/logs/directional_strangle_*/

**Order of work:** R2 + R1 first (correctness/safety, must be live before next session)
→ R5 → R3 → R4. Paper-only throughout (`LIVE=0`); never read/write `backend/.env`.
