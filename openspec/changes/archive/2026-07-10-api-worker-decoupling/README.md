# api-worker-decoupling

**Minimal context set** (load only these when working this change):
- `proposal.md`, `design.md` (GOVERNANCE 5-phase), `tasks.md`, `specs/api-worker-decoupling/spec.md`
- Backend: `backend/pdp/main.py` (lifespan to refactor), `market/router.py` + `market/ws.py`
  (hot path + WS bridge), `orders/` (command channel), `risk/service.py` (kill), `indicators/` +
  `portfolio/service.py` (snapshots), `db/session.py` + `mongo/client.py` (pools), `settings.py`,
  new `pdp/runtime/`
- Infra: `infra/compose/docker-compose.yml`
- Ratified constraint this satisfies: `openspec/specs/repo-architecture/spec.md` — "the strategy
  worker SHALL remain a separately-launchable process decoupled from the API"
- Feeds: `openspec/changes/cloud-deploy-aws` (its Docker/compose 3-service layout comes from here)

**Ship order:** last. Depends on change #1 (validated API tier that enqueues order commands) and
change #4 (warmup-disarm events). The Redis tick/bar bus it relies on already exists in
`market/router.py`.
