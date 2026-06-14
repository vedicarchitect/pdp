## 1. Remove look-ahead from fill pricing

- [x] 1.1 Flip-close (`backtest_multiday.py` ~`:822`): change `price_at(flip_bars, ist_dt, prefer="open")` to price the exit at the flip bar's **close** (`prefer="close"`), so the exit is not booked at the pre-signal open
- [x] 1.2 New/flip entry (~`:851`): change the entry `price_at(new_bars, ist_dt, prefer="open")` to the same convention (fill at the signal bar's close), keeping entries and exits consistent
- [x] 1.3 Scale-in (~`:871`): change the add `price_at(new_bars, ist_dt, prefer="open")` to close-based pricing
- [x] 1.4 Square-off / parity paths (`:799`, `:888`): confirm they price at close (squareoff already prefers open→close fallback) and align them with the no-look-ahead rule
- [x] 1.5 `price_at` (~`:139`): ensure the ±15-min nearest-bar tolerance cannot select a bar **later** than the requested timestamp for an exit (cap forward reach for exits), so a missing bar never yields a future (look-ahead) price

## 2. Tests

- [x] 2.1 Unit: a flip exit is filled at the flip bar's close, not its open (construct a position + a flip bar where open != close and assert the booked exit price == close)
- [x] 2.2 Unit: a synthetic favorable-reversal flip bar (open high, close low for a short PE/CE seller) no longer books the pre-reversal open as profit
- [x] 2.3 Unit: `price_at` for an exit does not return a bar later than the requested timestamp when the exact bar is missing

## 3. Verification

- [x] 3.1 Re-run `uv run python backtest_multiday.py --days 76 --start <same end>`; record the corrected profit factor, win rate, and net vs the prior PF 33.5 / 93% / +1.78M
- [x] 3.2 Re-dump 2026-02-26 leg summary; flip-leg P&L magnitudes drop (no pre-reversal capture)
- [x] 3.3 Update memory ([[supertrend-coldstart-gap]] / backtest_multiday_state) to mark PF 33.5 superseded by the corrected, look-ahead-free run
- [x] 3.4 `openspec validate --strict backtest-fill-timing-no-lookahead`
