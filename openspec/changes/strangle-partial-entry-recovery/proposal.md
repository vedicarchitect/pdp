# strangle-partial-entry-recovery

## Why

On 2026-07-15 live paper trading, the Dhan market-feed websocket was rejected with `HTTP 429`
for ~36 minutes after the API restarted mid-session (feed outage, spot = 0.0, `feed_stale`
every second). When the feed reconnected (~10:23 IST), all three strangle strategies re-evaluated
and confirmed a **neutral** bucket, whose ratio is a balanced 3-PE / 3-CE strangle. Each then
called `_open_bucket()`, which opens the **PE side first, then CE** (`directional_strangle.py:968`).

The entry fills came back with a **zero price** because the target option contracts had not yet
received a live tick after the reconnect — `_resolve_fill_price()` exhausted all four layers
(broker avg, in-process LTP cache, Redis feed LTP) and returned `None`, logging `fill_avg_px_zero`
(`:1007`). `_open_short()` correctly **aborts** a leg whose entry price is unresolvable rather than
booking `entry_price = 0` (`:1064-1076`) — that safety, added in `strangle-close-path-atomicity`,
worked: **no phantom P&L**. But the aborted side is never retried. The result was a lopsided book:

| Index | Attempted | Fill result | Outcome |
|-------|-----------|-------------|---------|
| NIFTY | close rehydrated PE legs (bucket_change) → open PE+CE | both fills = 0 (sids 63944, 63951) | **flat** |
| BANKNIFTY | open PE+CE | both fills = 0 (61888, 61895) | **flat** |
| SENSEX | open PE (829489) + CE (824353) | PE = 0 → aborted; CE tick'd → filled 186.11 | **CE-only** |

The book does **not** self-heal this session. New legs are opened **only on a bucket *change***
(`:634`); when the bucket matches the current one, the code takes the `else` branch (`:656`) and does
nothing. All three strategies are now parked in `neutral`, so the missing SENSEX PE side and the flat
NIFTY/BANKNIFTY books will not be retried until a bucket flips away and back. A transient,
per-contract entry failure (feed reconnect, a single rejected order, a momentarily cold LTP) thus
silently degrades the intended risk shape for the rest of the day — a directional call-spread instead
of the intended neutral strangle.

## What Changes

- Add **intended-composition tracking** to the live `DirectionalStrangle`: when it acts on a bucket,
  it records the desired short-lot count per side and which sides have been *realized* (successfully
  opened at least once) in this bucket episode.
- Add a **recovery pass** that runs on each decision bar while the bucket is unchanged: for any side
  the bucket requires that currently has **no open short leg** and was **not** exited by a
  take-profit / stop / roll this episode (i.e. never realized, and not stop-gated), attempt to open
  the shortfall — reusing the existing `_open_short()` path (per-sid lock, `_reserve_leg_lots` cap,
  protective hedge). This makes a partial/aborted entry self-correct within the same bucket.
- **Bound** the recovery: at most `entry_recovery_max_attempts` (default 3) per side per bucket
  episode. On exhaustion emit a terminal `ENTRY_SIDE_UNFILLED` observability event and stop retrying
  that side until the next bucket change. Each attempt is logged.
- Recovery **never** resurrects a leg that was deliberately closed (take-profit banks a side, a stop
  gates it, a roll manages it) — only sides that never opened this episode are recovered.

Scope is the **live strategy only**. The backtest simulator fills deterministically and does not hit
this failure mode, so `bias.py` and `strangle_sim.py` are untouched; identical bias decisions are
preserved.

## Impact

- Affected spec: `directional-strangle` (ADDED requirement — entry-side recovery).
- Affected code: `src/pdp/strategies/directional_strangle.py` (entry decision path + new reconcile
  helper + episode state). New config keys `entry_recovery_enabled` (default true) and
  `entry_recovery_max_attempts` (default 3) via `StrategyConfig`.
- Related: complements `strangle-close-path-atomicity` (abort-instead-of-zero) and
  `strangle-leg-state-durability`; new event ties into `strangle-observability-gaps`.
- Paper-only change; no `LIVE=1` at any point.
