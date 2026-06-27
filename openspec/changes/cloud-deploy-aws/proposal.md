## Why

Local Docker is getting slow; the near-future target is a cost-effective AWS deployment with seamless, repeatable deploys.

> **Stub** — part of the PDP program roadmap (see root `CLAUDE.md`). This is a thin
> placeholder; it gets a full `design.md` + `specs/` + detailed `tasks.md` in its own
> interactive design session before implementation.

## What Changes

Cost-effective AWS via Terraform: containerize the API + strategy worker, decide managed vs self-hosted PG/Redis/Mongo, and a CI build->push->deploy pipeline. Lands in the reserved infra/terraform + infra/deploy.

## Capabilities

### New Capabilities
- `cloud-deploy-aws`: see the full design session for requirements.
