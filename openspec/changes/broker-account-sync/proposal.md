## Why

Track everything the broker reports. Today nothing persists the daily Dhan account state, so historical holdings/positions/funds are lost the moment they change.

> **Stub** — part of the PDP program roadmap (see root `CLAUDE.md`). This is a thin
> placeholder; it gets a full `design.md` + `specs/` + detailed `tasks.md` in its own
> interactive design session before implementation.

## What Changes

Idempotent end-of-day Dhan sync (via the `dhanhq` skill) capturing holdings, positions, orderbook, tradebook, funds and ledger into the PostgreSQL ledger (current) + MongoDB history (immutable daily snapshots).

## Capabilities

### New Capabilities
- `broker-account-sync`: see the full design session for requirements.
