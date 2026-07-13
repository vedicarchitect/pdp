# strangle-observability-gaps — minimal context

Read only these. **Land this last** — it aggregates signals the four preceding changes produce.

| File | Why |
|------|-----|
| `backend/pdp/strategies/directional_strangle.py` | `_emit_event:604-624`; `POSITION_SIZE_CAPPED` at `:1157`, `:1370`, `:1422`, `:1616`, `:1634` |
| `backend/pdp/events/models.py` | `POSITION_SIZE_CAPPED:85`; add `STRATEGY_NOT_READY` |
| `backend/pdp/mongo/collections.py` | `get_events_collection:361` — two readers, zero writers |
| `backend/pdp/market/bar_writer.py` | The batching fire-and-forget pattern to mirror |
| `backend/pdp/strategy/routes.py` | `:332` reads the events collection; readiness endpoint lands here |
| `backend/tests/strategy/test_directional_strangle.py` | `:953, :979, :1003, :1025` assert the overloaded event name |
| `infra/opensearch/` | Dashboards keyed on the current event taxonomy |

## Key facts established during investigation
- `POSITION_SIZE_CAPPED` is emitted from **five sites for three unrelated conditions**: cap clip
  (`:1616`, `:1634`), leg-direction contradiction (`:1370`, `:1422`), momentum (`:1157`). A risk limit
  working as designed and a data-corruption alarm share one channel, name and severity.
- `_emit_event` fans out to structlog, a JSONL file (`self._slog`) and an in-memory `_activity` deque.
  **It never writes a database.** That is why `_rehydrate_legs`'s Mongo `leg_open` query always
  returns nothing — see `strangle-leg-state-durability`.
- The four existing test assertions check `POSITION_SIZE_CAPPED` by name and would survive the split
  silently. Update them as part of the rename.
- Readiness inputs already exist after the preceding changes; nothing aggregates them. On 2026-07-09
  the strategy opened at 09:15 with an unseeded EMA(200), two abstaining bias inputs, a stale broker
  mirror and un-reconciled legs.
- `_emit_event` is called from `on_tick`. Any durable sink must batch, not await.

## Related
`[[opensearch_log_pipeline]]`, `[[event_publisher]]`.
Fixed elsewhere, do not duplicate: `stop_half`/`stop_all` exit fields (already fixed in `f045282`),
SENSEX PCR (`bias-input-completeness`), EMA(200) null (`indicator-history-depth`).
