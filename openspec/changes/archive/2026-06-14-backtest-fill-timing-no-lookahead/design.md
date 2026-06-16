## Context

`backtest_multiday.py` replays NIFTY 1m spot resampled to the signal timeframe, computes
SuperTrend(3,1) per bar, and trades a reverse-bias premium-selling strategy. The bar loop
(`backtest_multiday.py:787`) iterates `(ist_dt, bar_open, bar_close, st)` where `st` is the tracker
state produced from **this bar's high/low/close** (`tracker.update(...)`, `:723`). Therefore
`st.flipped` / `st.direction` for a bar are only knowable **at that bar's close**.

The strategy's profit is concentrated in **flip** events: when ST reverses, the held leg is closed and
an opposite leg opened. The audited 2026-02-26 day (+39,291) shows every leg exiting on `flip` with
strongly asymmetric magnitudes (winners +5k…+13k, losers −0.6k…−0.9k).

## Problem

All four fill sites price at the **bar's open**:

| Site | Line | Call |
|------|------|------|
| Flip-close | ~822 | `price_at(flip_bars, ist_dt, prefer="open")` |
| New/flip entry | ~851 | `price_at(new_bars, ist_dt, prefer="open")` |
| Scale-in | ~871 | `price_at(new_bars, ist_dt, prefer="open")` |
| Squareoff | 799/888 | `prefer="open"` then close fallback |

Because the flip is decided by bar N's **close** but filled at bar N's **open**, the exit captures the
premium *before* the reversal that triggered it — a one-bar (5-min) look-ahead. The existing `backtest`
spec already requires "fill at the bar's close price at end of bar processing"; the implementation
contradicts it.

## Decision: fill at the signal bar's close

Adopt **fill-at-close** for the bar that produces the decision. Rationale:

- It is exactly what the existing spec states, so this is a conformance fix, not a new convention.
- It matches live/paper, where the indicator engine emits a signal on a **completed** bar and the
  strategy acts at/after that close — so backtest and live become causally aligned (parity work).
- It is the minimal change: flip the four `prefer="open"` to `prefer="close"` and harden `price_at`.

Considered and rejected: **fill at next bar's open**. Marginally more conservative (models the gap
between seeing the close and trading the next bar) but (a) diverges from the spec's stated close-fill
rule, (b) needs the loop to carry the decision to the next iteration (more invasive), and (c) the
live engine acts on the closing bar's value, so close-fill is the better parity match. Next-open can be
revisited later as a slippage/latency refinement; it is not needed to remove the look-ahead.

### Harden `price_at` against forward reach

`price_at` picks the nearest bar within ±15 min in **either** direction. With dense option data this
rarely fires, but for an **exit** a future bar would itself be look-ahead. Cap the forward window for
exit pricing (or pass a direction hint) so a missing bar resolves to the nearest **prior-or-equal**
bar, never a later one. Entries may keep symmetric tolerance (their look-ahead is neutral-to-adverse),
but applying the prior-or-equal cap uniformly is simplest and safe.

## Risks / trade-offs

- **PF will drop**, likely sharply — that is the intended correction; the prior figure was inflated by
  the look-ahead. Memory and any reported results must be updated.
- **Close-vs-open on entries** slightly changes entry basis; net effect is small and removes the
  inconsistency of mixing open-fills with close-driven signals.
- **No live/paper impact** — the live path already acts on closed bars; this only changes the backtest
  simulator.

## Verification

- Unit: a constructed flip bar with `open != close` books the exit at `close`; a favorable-reversal bar
  no longer yields pre-reversal profit; `price_at` for an exit never returns a later-than-requested bar.
- Integration: re-run 76-day backtest; record corrected PF / win-rate / net; re-dump 2026-02-26 legs.
