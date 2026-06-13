## MODIFIED Requirements

### Requirement: Flip closes and reverses
The strategy SHALL, when the SuperTrend direction flips against the open leg, buy back the open
leg and open the opposite-side leg at the starting lot size. The new-leg SELL SHALL only be placed
after the close order has left the strategy with zero net position: the strategy SHALL read
`net_qty` from the positions table after placing the BUY and SHALL skip the new-leg open on the
current bar if `net_qty` is still non-zero. A skipped open on flip is retried on the next bar's
signal provided the position has since flattened.

#### Scenario: Up-to-down flip
- **WHEN** a short PE leg is open and SuperTrend flips to down
- **THEN** the strategy buys back the PE and sells the OTM CE at the starting lot size

#### Scenario: Flip open skipped if close not yet confirmed
- **WHEN** the BUY (close) order has been placed but `net_qty` for the old security is still non-zero at the time `_open()` would be called
- **THEN** the new-leg SELL is NOT placed on this bar; `_current` remains None; the strategy logs `flip_open_deferred`

#### Scenario: Deferred open retried on next bar
- **WHEN** the flip open was deferred on bar N and by bar N+1 the position is flat (`net_qty == 0`)
- **THEN** the strategy opens the new leg at bar N+1's signal as if entering fresh

---

### Requirement: Scale-in while trend holds
The strategy SHALL add a configured number of lots on each subsequent signal bar while the
SuperTrend direction is unchanged, up to a configured maximum lot count. The effective open lot
count used for the max-lots cap SHALL be derived from the positions table (`abs(net_qty) // lot_size`)
at the start of each `on_bar()` evaluation, not solely from an in-memory counter, so that restarts
and partial fills do not cause the cap to be evaluated against a stale value.

#### Scenario: Add a lot on continued trend
- **WHEN** a leg is open, the direction is unchanged on a new bar, and open lots < max
- **THEN** the strategy sells `add_lots` more of the same option

#### Scenario: Respect the max-lots cap — position-table derived
- **WHEN** the positions table shows `net_qty` corresponding to `max_lots` already sold
- **THEN** the strategy does not add more lots, even if the in-memory counter was reset by a restart

#### Scenario: Lots sync on recovery after restart
- **WHEN** the server restarts mid-session, `_current` is recovered from the ledger, and the positions table shows 3 lots short
- **THEN** the effective lots count for the scale-in cap is 3 (from positions table), not whatever the recovered `_current["lots"]` states

---

### Requirement: Per-leg stop-loss
The strategy SHALL, on each closed signal bar before evaluating flip or scale-in, compute the
open leg's unrealized mark-to-market loss from its average entry price and the option's latest
price, and SHALL buy back the entire leg at market when that loss reaches or exceeds a
configured per-lot amount multiplied by the current open lot count (`leg_stop_per_lot × open_lots`).
The per-lot amount SHALL be configurable via `params`, defaulting to 1000. After a stop-driven
close the strategy SHALL place no new entry on the same bar; re-entry is decided by a subsequent
bar's signal.

The mark price SHALL be the open *option's* latest Redis LTP. Because the strategy is driven by
the NIFTY *index* bar, the bar's `close` is the spot level and is NOT a valid mark for the option
premium; the strategy therefore SHALL NOT substitute `bar.close` for the option price. If the
Redis LTP is absent, non-positive, OR its recorded timestamp is older than a configurable
staleness threshold (default 30 seconds), the strategy SHALL skip the stop evaluation on that bar
(leaving the leg open for a later bar with a fresh quote) and SHALL log `leg_stop_ltp_stale_fallback`.

#### Scenario: Leg stop triggers a close
- **WHEN** a leg of `n` lots is open and its unrealized loss (marked on a fresh option LTP) reaches `leg_stop_per_lot × n`
- **THEN** the strategy buys back the full leg at market with a `leg_stop` reason and opens no new leg on that bar

#### Scenario: Loss below threshold holds the leg
- **WHEN** the open leg's unrealized loss is less than `leg_stop_per_lot × open_lots`
- **THEN** the strategy does not close the leg for stop reasons and proceeds to its normal flip / scale-in logic

#### Scenario: Stale or missing option LTP skips the stop
- **WHEN** the Redis LTP for the open option is missing, non-positive, or its timestamp is older than the staleness threshold
- **THEN** the strategy does not evaluate a stop on that bar, leaves the leg open, and logs `leg_stop_ltp_stale_fallback`

#### Scenario: Fresh option LTP marks the leg
- **WHEN** the Redis LTP for the open option is present and its timestamp is within the staleness threshold
- **THEN** the strategy marks the leg against that LTP and trips the stop only when the resulting loss reaches the limit
