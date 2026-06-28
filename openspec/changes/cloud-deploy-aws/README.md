# cloud-deploy-aws

**Minimal context set** (load only these when working this chunk):
- infra/terraform/ (reserved), infra/deploy/ (reserved), infra/compose/
- cloud-readiness reqs in repo-architecture spec
- backend/pdp/observability/ (chunk 5 log pipeline) — prod swaps to AWS OpenSearch Service via `OPENSEARCH_URL` env var; no code change required
- infra/opensearch/ — dashboards NDJSON imported via `task search:init` after provisioning
