# Design: backtest-leg-grouped-summary

## Approach

Extend `backtest_multiday.py` output-only — no simulation logic changes.

**Decision: accumulate legs inside `simulate_day`**

Each call to `close_position` now records a leg dict into a `day_legs` list:

```python
{"type": CE/PE, "strike": int, "entry_ist": str, "exit_ist": str,
 "lots": int, "avg_entry": Decimal, "exit_price": Decimal,
 "leg_pnl": Decimal, "reason": str}
```

Scale-ins fold into the parent leg via running weighted average:
`avg_entry = (avg_entry * old_lots + price * new_lots) / total_lots`

**Decision: separate `print_day` section**

`print_day` renders the existing per-order table unchanged, then appends a
`LEG SUMMARY` block using `tabulate`. Footer shows: leg count, total P&L, win/loss counts.

## Validation

Leg total P&L must equal the per-order `Net premium` — verified by a live 2026-06-11
backtest run (11 legs, total +28,447.25 = per-order sum).
