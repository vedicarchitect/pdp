# PDP — Agent Guidance

This project is **spec-driven via OpenSpec**. The source of truth for every capability lives under `openspec/specs/<capability>/spec.md` (after archival) and `openspec/changes/<change-id>/` (while in flight).

## Non-negotiables

1. **Spec-first.** No new feature without a proposal under `openspec/changes/`.
   - Use `/opsx:propose "<idea>"` (or `openspec new change <id>`) to start.
   - Validate with `openspec validate --strict <change-id>` before coding.
2. **Paper-first.** Orders route to the paper engine unless `LIVE=1` env var is set AND a broker is configured. Live trading is never the default.
3. **One mutation per route.** API endpoints do one thing.
4. **Universal indicators.** Indicators / levels / value-areas are computed once by the market engine and persisted; strategies consume them — they do not recompute.
5. **Latency.** Tick → WebSocket fan-out p99 ≤ 50ms. No blocking calls on the hot path.
6. **No bare `print()` / `rich`** inside core modules. Use `structlog`.

## Workflow

1. `openspec list` — see active changes.
2. `openspec show <change-id>` — inspect a proposal.
3. After implementing: `openspec archive <change-id>` to promote deltas into `openspec/specs/`.

## Project profile

See [openspec/project.md](openspec/project.md) for tech stack, conventions, and layout.
