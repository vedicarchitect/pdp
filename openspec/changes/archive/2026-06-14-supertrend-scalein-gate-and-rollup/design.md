## Context

The premium-selling strategy holds one short option leg per side, computed on closed SuperTrend bars.
In the backtest (`backtest_multiday.py`) the per-bar decision order is:
square-off -> per-leg stop (at bar close) -> flip (close + reverse) -> wait-for-first-flip gate ->
new entry / scale-in. The held `Position` accumulates `total_qty`, `total_cost`, `lots`, and a
derived `avg_entry`; `close_position` settles `pos.total_qty` at `pos.avg_entry`.

Three behaviors are added/changed, all strategy-level (capability `supertrend-strategy`), so the spec
governs both the backtest's embedded strategy and the live/paper strategy.

## Decision 1: gate scale-in on the leg's premium breakout

Add a lot only when the open leg's option premium did NOT make a new high on the current bar versus
the immediately preceding bar (`current_bar.high <= prior_bar.high`). If the prior high is broken
(premium spiking against the short), defer and re-check the same gate every subsequent bar; add on
the first bar that fails to break the prior high, still capped by max lots. With no prior bar, allow.

- Rationale: averaging into a leg whose premium is making new highs is averaging into an adverse,
  often-transient spike; waiting for the spike to stall avoids the worst add prices.
- Candle source: the **option premium** candle of the held leg (`_pos_bars(pos)`), not the NIFTY
  spot candle - the gate is about the position's own adverse momentum and "recovery" (premium
  falling back). Tuple shape is `(dt, o, h, l, c)`; index 2 is the high.
- A new `prev_curr_bars(bars, target)` helper returns `(prior_bar, current_bar)` - the nearest bar to
  `target` within the existing tolerance plus its immediate predecessor in time.

## Decision 2: premium-decay roll-up

When the open leg's premium (bar close) falls below `ROLL_TRIGGER_PREM` (default 20) and the
SuperTrend direction is unchanged, buy back the whole leg and re-sell the **furthest-OTM same-side
strike whose current premium exceeds `ROLL_TARGET_MIN_PREM` (default 50)**, opening at the starting
lot count. Scale-in then re-arms for the new leg.

- Target selection: scan same-side strikes within the warehouse band from furthest-OTM inward toward
  ATM; pick the furthest-OTM strike whose premium > 50. This keeps the new leg as OTM (lowest delta)
  as possible while still harvesting >50 of fresh premium - the natural reading of "rollup to atm or
  otm if premium > 50". (ATM-only and nearest-just-over-50 were considered; furthest-OTM>50 is the
  lowest-risk re-entry that meets the floor. Revisit in review if a different target is wanted.)
- No qualifying strike: if no same-side strike in the band clears 50 (low-vol/late day), do not roll;
  hold the existing cheap leg (square-off handles end-of-day).
- Ordering: roll-up is evaluated only when the direction is unchanged and there is no flip. A flip
  against the leg takes precedence (reverse, not roll). Roll-up is checked before scale-in so the
  strategy never adds to a leg it is about to roll, and the roll bar opens at starting lots only
  (no same-bar scale-in), mirroring the flip/stop "no new add on the action bar" discipline.
- Lots on the rolled leg: reset to `START_LOTS` (fresh leg), per decision; the gate re-arms.

## Decision 3: closes settle the exact held quantity

Every close path - flip, per-leg stop, daily-cap flatten, roll-up, square-off (intraday and
end-of-loop) - buys back exactly `pos.total_qty` at `pos.avg_entry`. This is already how
`close_position` behaves; the design makes it an explicit invariant because the gate (deferred adds)
and roll-up (reset to starting lots at a new strike) now make held quantity dynamic.

- Invariant preservation: held quantity changes only through `pos.add(...)`; the gate must gate the
  `pos.add` call itself (never a side counter), so a deferred add leaves `total_qty` untouched. A
  roll must `close_position` the full leg (settling `total_qty`) and then construct a fresh
  `Position`, so no partial/assumed quantity is ever carried.

## Risks / trade-offs

- Fewer scale-in adds on choppy days -> lower per-leg size and different P&L; intended.
- Roll-ups add same-side round-trip commission and re-establish risk closer to ATM; net effect is
  empirical and recorded on re-run.
- Live/paper must adopt the same rules to keep parity; this change specs the behavior once. Live
  implementation is sequenced under the live-backtest parity initiative, not this change.

## Verification

- Unit: premium breakout defers an add; a later non-breakout bar adds. Roll-up at premium<20 re-sells
  the furthest-OTM strike with premium>50 at starting lots, and does not roll when none clear 50.
  After gated adds and a roll, a flip/square-off close buys back exactly the held quantity.
- Integration: re-run the multiday backtest; record scale-in count, roll count, PF/win/net deltas.
