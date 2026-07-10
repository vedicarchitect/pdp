# strangle-close-path-atomicity — minimal context

Read only these to work this change. **Paper-only. Never set `LIVE=1` while working it.**

| File | Why |
|------|-----|
| `backend/pdp/strategies/directional_strangle.py` | The whole change. Key spans below. |
| `backend/pdp/orders/router.py` | `get_net_qty`, `cancel_open_entry_orders`, `place` — what the close path calls |
| `backend/pdp/orders/paper.py` | When a paper fill becomes visible to `get_net_qty` (the race window) |
| `backend/pdp/events/models.py` | `POSITION_SIZE_CAPPED` exists; add `LEG_STATE_DIVERGED` |
| `backend/pdp/strategies/CLAUDE.md` | Strategy conventions |

## Line map (as of `f6030a6`)
| Span | What |
|------|------|
| `:262` | `self._rolling: set[str]` |
| `:505`, `:512` | `on_tick` iterates `_short_legs + _hedge_legs + _momentum_legs` |
| `:519` | Roll guard — `ltp < roll_trigger_prem and sid not in self._rolling` |
| `:523-529` | `take_profit` close + `_close_matching_hedge` |
| `:531-544` | `stop_half` — mutates `leg.lots` in place |
| `:879`, `:1898` | `self._short_legs.append(leg)` — the two places a duplicate sid can enter |
| `:1129` | `_close_momentum_leg` |
| `:1181-1257` | `_roll_leg` — **`add(sid)` at `:1184`**, close at `:1189-1190`, spot check at `:1193` |
| `:1299` | `_close_all` — iterates the in-memory lists only |
| `:1326-1384` | `_close_short_leg` — `net_qty` read `:1353`, `close_lots` `:1357`, place `:1378`, identity removal `:1384` |
| `:1386` | `_close_hedge_leg` |
| `:1438` | `_close_matching_hedge` |
| `:1447` | `state()` |
| `:1772` | `_rehydrate_legs` |

## Key facts established during investigation
- The open path (`_open_short`/`_open_hedge`/`_open_momentum`) holds `_lock_for(sid)`. **The close
  path holds nothing.** Guarding one side of a read-modify-write is not mutual exclusion.
- `_roll_leg` closes the short *and its hedge* before checking `spot is None`. All three `skipped_*`
  branches leave the book flat and unhedged while reporting a roll.
- `close_lots = abs(net_qty) // lot_size` closes the **security's** whole position; removal is by
  object identity. The two disagree whenever two `OpenLeg`s share a `security_id`.
- `asyncio.Lock` is **not re-entrant**. `_roll_leg → _close_short_leg → _open_short` on one sid will
  deadlock if each naively acquires. Design the lock discipline before writing code.
- Live evidence: NIFTY 63993 18→4,608 lots (11 roll retries); SENSEX 822316 12→12,288; SENSEX 821960
  33→528 with **no roll event at all**; SENSEX 821946 reopened by two BUYs 3 ms apart.
- **Unexplained:** legs vanished from all three in-memory lists while the broker position stayed open
  at 16 lots. `_close_all` would have missed it. Reproduce (task 1.8) before fixing.

## Related
`[[leg_rehydration_misclassification_bug]]`, `[[position_size_cap_and_lock_race]]`.
Distinct from `strangle-leg-state-durability`: this change makes the close path atomic for a
*correctly classified* leg; that one makes classification survive a restart. Both are required.
