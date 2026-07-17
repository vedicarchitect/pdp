# strangle-entry-fill-race-and-latch

## Why

On 2026-07-17 (a live paper session), NIFTY and BANKNIFTY opened **zero legs all day** while the
strategy was otherwise healthy — running, heartbeating, and evaluating bias every 5m with a valid
directional bucket (`more_bull`, score +0.5..+0.59, `gated:false`, EMAs not abstaining). SENSEX
opened one leg. The strangle activity log showed only `bias_evaluated` / `leg_status legs:[]`,
which reads as "nothing happening" and made the failure look like an indicator/warmup problem.

Read-only live diagnosis (Redis + Postgres + OpenSearch) proved otherwise:

- Instruments are present (NIFTY 2026-07-28 options + exact OTM strikes; `lot_size` resolves), the
  option feed is live (option `ltp:*` keys in Redis), VIX is live (`ltp:21`), and indicator
  snapshots publish. None of these is the blocker.
- `fill_avg_px_zero` fired **6×** that day. This is the terminal fallback in
  `DirectionalStrangle._resolve_fill_price` — at open time the just-subscribed OTM option had no
  resolvable LTP within the ~1.2s fill-resolution budget (broker fill hadn't happened, in-process
  LTP cache empty, market-feed `ltp:<sid>` not yet populated), so `_open_short` **aborted the leg**.

Two code defects combine into a full-day outage:

1. **Subscribe→fill race.** `_open_short` subscribes the option (`ctx.market.subscribe`) and then,
   within ~1.2s, demands a fill price. A freshly-subscribed F&O instrument frequently has not
   produced its first tick that fast, so the paper MARKET order stays `OPEN` (unfilled) and every
   fallback layer is cold → the leg aborts.
2. **One-shot latch.** In `on_bar`, `self._current_bucket` is set to the new bucket **before**
   `_open_bucket` runs. So once a bucket is "confirmed", a transient open failure latches the
   bucket anyway and `_open_bucket` is **never called again** for the rest of the day — no retry
   even after the option starts ticking seconds later. SENSEX won the race for one leg;
   NIFTY/BANKNIFTY lost it and stayed flat all day.

The failure was also **invisible**: `fill_avg_px_zero` and the abort go to stdout/structlog, not
the strategy activity log or the monitor payload, so the Execution Console gave no signal that an
entry had been attempted and aborted.

## What Changes

- **Commit the bucket transition only on a filled open.** `_open_bucket` / `_open_short` /
  `_open_hedge` return how many legs actually opened. `on_bar` advances `_current_bucket` (and
  clears the pending-confirmation counter) **only when at least one leg opened**. On a transient
  open failure the pending bucket is retained so the next 5m bar retries the open. DTE-gated bars
  (a legitimate no-trade) likewise do not latch.
- **Close the subscribe→fill race.** After subscribing an option and before aborting, `_open_short`
  waits (bounded, configurable `entry_ltp_wait_s`, default a few seconds) for the option's first
  LTP so the paper/live MARKET order can fill on the first tick instead of aborting cold.
- **Make aborts loud.** Add a first-class `ENTRY_ABORTED` strangle event (with the bucket,
  requested PE/CE lots, and reason) emitted into the activity log + monitor payload, so a silent
  no-trade can never again masquerade as "nothing happening".

Out of scope: warmup/DH-905 (separate change `indicator-warmup-derive-from-1m`), the readiness
Indicators-component bug (`strangle-readiness-indicators-truthful`), and UI freshness / `/events`
(`execution-panel-freshness-and-events`). VIX plumbing is untouched (gate disabled by config).

## Impact

- Affected specs: `directional-strangle` (bucket-confirmation + a new atomic-open requirement +
  status-logging of aborts).
- Affected code: `backend/pdp/strategies/directional_strangle.py` (`on_bar`, `_open_bucket`,
  `_open_short`, `_open_hedge`, `_open_momentum` return contracts), `backend/pdp/strategy/log.py`
  (`StrangleEventType.ENTRY_ABORTED`). No schema/migration changes. Paper broker behavior unchanged.
