## Context

`backtest_multiday.py` currently computes charges as:

```python
charges = sum(1 for t in trades if t.side == "BUY") * 2 * 7.25
```

This is a flat `₹14.50 × number_of_round_trips` — a rough proxy that understates costs for large-notional trades (STT on a single lot of NIFTY options at ₹100 = ₹750 in notional → ₹0.75 in STT, but at ₹500 notional per lot × 75 = ₹37,500 turnover → ₹37.50 in STT per lot). For a 3-lot straddle with two legs the real cost is 5–15× the current estimate.

The `BacktestEngine` in `src/pdp/backtest/engine.py` has no concept of commissions at all — it uses the `PaperBroker`-style fill model where P&L = premium received − premium paid, with no cost deduction.

## Goals / Non-Goals

**Goals:**
- Replace the ad-hoc `₹14.50` formula with a `CommissionCalculator` that computes each Indian cost component correctly per fill.
- Track `gross_pnl` (premium only) and `net_pnl` (after commissions) as separate values throughout backtest_multiday.py.
- Make all rates configurable in `settings.py` so future SEBI/exchange revisions need a one-line change.
- Provide a `--no-commission` CLI flag for raw-premium comparisons.

**Non-Goals:**
- Margin/leverage modeling (out of scope for this change).
- Support for equity or futures commission structures (options only for now).
- Integration with `BacktestEngine` (src/pdp/backtest/engine.py) in this change — that engine is currently only used for the engine unit tests, not by `backtest_multiday.py`. Wire-up to the engine is a follow-on.

## Decisions

### D1: New module `src/pdp/backtest/commissions.py`

Rather than embedding charge math in `backtest_multiday.py`, extract a `CommissionCalculator` class. This keeps the script at the "orchestration" level and makes the calculator independently testable.

**Alternative considered:** Inline the math as helper functions in the script. Rejected — the existing script is already 900 lines; a class is easier to test in isolation and reuse for future strategies.

### D2: Per-fill calculation, not per-day aggregate

Each `Trade` object has enough data (side, qty, price) to calculate commissions at fill time. Accumulate into a `commission_inr` field on `Trade` and sum at end of day. This aligns with how brokers charge (per order, per side) and enables per-leg cost attribution.

**Alternative considered:** Calculate once at end of day from total turnover. Rejected — loses per-leg visibility and makes it impossible to attribute cost to specific rolls vs. entry/exit.

### D3: Commission components and formulas

Based on NSE/BSE circular rates for F&O (options, sell-side):

| Component | Rate | Applied to | Side |
|-----------|------|-----------|------|
| Brokerage | ₹20 flat | Per order | Both |
| STT | 0.1% of premium | Turnover (qty × price × lot_size) | Sell only |
| Exchange Txn | 0.03553% | Turnover | Both |
| SEBI | ₹10 / ₹1 crore | Turnover | Both |
| Stamp Duty | 0.004% | Turnover | Buy only |
| GST | 18% | Brokerage + Txn + SEBI | Both |

`turnover = qty_in_contracts × lot_size × premium_per_unit`

**Note:** `qty` in `Trade` is already in units (e.g., 75 for 1 lot of NIFTY). So `turnover = trade.qty × trade.price`. The `lot_size` is embedded in `qty`.

### D4: `BacktestCommissionSettings` in `settings.py`

Group all rates under a nested `BacktestCommissionSettings` pydantic model so they can be overridden via environment variables (`BACKTEST_COMMISSION__STT_RATE=0.001`). Provide Indian-market defaults.

```python
class BacktestCommissionSettings(BaseSettings):
    brokerage_per_order: Decimal = Decimal("20.00")
    stt_rate: Decimal = Decimal("0.001")       # 0.1% sell-side
    txn_charge_rate: Decimal = Decimal("0.0003553")
    sebi_rate: Decimal = Decimal("0.000010")   # ₹10/crore = 0.00001
    stamp_duty_rate: Decimal = Decimal("0.00004")  # 0.004% buy-side
    gst_rate: Decimal = Decimal("0.18")
```

### D5: `backtest_multiday.py` output changes

- `Trade` dataclass gains `commission_inr: float = 0.0`.
- Day result dict gains `gross_pnl` (rename current `day_pnl`), `commission_total`, `realized` = `gross_pnl - commission_total`.
- Summary table gains `Gross`, `Comm`, `Net` columns.
- `--no-commission` flag: passes a `NullCommissionCalculator` that always returns `0`.

## Risks / Trade-offs

- [Complexity creep] The formula has 6 components — a small error in one (e.g., applying STT to both sides) silently inflates costs. → Mitigation: Unit tests for each component independently; also include an end-to-end fixture with known expected output.
- [qty semantics] `Trade.qty` is in absolute units (e.g., 75 = 1 NIFTY lot). If this assumption breaks, turnover will be wrong. → Mitigation: The caller (backtest_multiday.py) is responsible for passing correct turnover; `calculate()` only accepts pre-computed `turnover_inr` so a lot-size check is not feasible inside the calculator without coupling it to a specific underlying.
- [Backwards compatibility] Existing log/stdout format changes (new columns). → Acceptable — this is a local script, not an API.

## Migration Plan

1. Add `BacktestCommissionSettings` to `src/pdp/settings.py`.
2. Create `src/pdp/backtest/commissions.py`.
3. Update `backtest_multiday.py`: add `commission_inr` to `Trade`; call calculator on each fill; update output.
4. Add `--no-commission` flag to CLI.
5. Add `tests/backtest/test_commissions.py`.
6. No database migrations required.
7. Rollback: `--no-commission` flag always available for raw comparison.

## Open Questions

- None — all rates are publicly available from NSE/BSE circulars; the formula is deterministic.
