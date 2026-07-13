# strangle-leg-state-durability — minimal context

Read only these. **Do not start until `strangle-close-path-atomicity` lands.** Paper-only.

| File | Why |
|------|-----|
| `backend/pdp/strategies/directional_strangle.py` | `_rehydrate_legs:1772-1830`; dead Mongo read at `:1809-1821`; sign guard at `:1359-1377` |
| `backend/pdp/orders/models.py` | `Position:100` — keyed `(strategy_id, security_id)`, **no leg-type column** |
| `backend/pdp/mongo/collections.py` | `get_events_collection:361` — the collection nothing writes |
| `backend/pdp/strategy/routes.py` | `:332` — the *other* read of that collection; audit it |
| `backend/pdp/events/models.py` | `POSITION_SIZE_CAPPED` today; add the two new event types |
| `backend/alembic/` | The one migration in this sequence |

## Key facts established during investigation
- `get_events_collection` has **exactly two callers repo-wide** (`directional_strangle.py:1815`,
  `strategy/routes.py:332`) and **both are reads**. `_emit_event` writes structlog / JSONL /
  OpenSearch / in-memory `_activity` — never Mongo. So `leg_open_by_sid` is always `{}` and every
  rehydrated leg is classified `short`.
- `Position` has no `is_hedge` / `is_momentum` / `leg_kind` column. A better Mongo query cannot fix
  this; only a column can.
- Live 2026-07-09: SENSEX hedge sid 822169 (genuinely long) restored as short → `_close_short_leg`
  issued BUY → 4 → 8 → 16 lots over three restarts.
- `f045282` patched the symptom (`net_qty`-sign-derived close side + `POSITION_SIZE_CAPPED`). Keep it,
  but a sign contradiction *after* this change means the durable store is wrong — escalate, don't
  just log.
- `:1781` returns early when any leg list is non-empty. A partial restore silently leaves positions
  unadopted and therefore invisible to `_close_all`.
- `execution-console-daily-parity` is **implemented, 23/23, unarchived**. It already fixed
  `entry_price=0`, the `avg_price` re-base and the DB-first ledger. Do not redo that work.

## Related
`[[leg_rehydration_misclassification_bug]]`, `[[execution_daily_parity]]`,
`[[dead_command_channel_import]]` — the same class of defect: a reader of something nothing writes,
failing silently for weeks.
