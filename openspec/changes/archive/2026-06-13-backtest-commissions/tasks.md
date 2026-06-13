## 1. Settings

- [x] 1.1 Add `BacktestCommissionSettings` nested model to `src/pdp/settings.py` with all 6 rate fields and NSE defaults (`brokerage_per_order=20`, `stt_rate=0.001`, `txn_charge_rate=0.0003553`, `sebi_rate=0.00001`, `stamp_duty_rate=0.00004`, `gst_rate=0.18`)
- [x] 1.2 Wire `BacktestCommissionSettings` into the root `Settings` model as `backtest_commission: BacktestCommissionSettings = BacktestCommissionSettings()`

## 2. CommissionCalculator module

- [x] 2.1 Create `src/pdp/backtest/commissions.py` with `CommissionBreakdown` dataclass (fields: `brokerage`, `stt`, `txn_charge`, `sebi`, `stamp_duty`, `gst`, `total_inr` — all `Decimal`)
- [x] 2.2 Implement `CommissionCalculator` class with `__init__(self, settings: BacktestCommissionSettings)` and `calculate(self, side: str, turnover_inr: Decimal) -> CommissionBreakdown`
- [x] 2.3 Implement `NullCommissionCalculator` with the same `calculate` signature, always returning a zero `CommissionBreakdown`
- [x] 2.4 Verify STT is sell-side only, stamp duty is buy-side only, GST applies to (brokerage + txn + SEBI) only

## 3. Tests for CommissionCalculator

- [x] 3.1 Create `tests/backtest/test_commissions.py`
- [x] 3.2 Test sell-side 1 NIFTY lot at ₹100 (turnover=7500): assert each component matches expected value within ₹0.01
- [x] 3.3 Test buy-side 1 NIFTY lot at ₹100: assert STT=0, stamp_duty>0
- [x] 3.4 Test zero turnover: assert total = brokerage only (₹20)
- [x] 3.5 Test `NullCommissionCalculator` returns all zeros

## 4. backtest_multiday.py integration

- [x] 4.1 Add `commission_inr: float = 0.0` field to `Trade` dataclass in `backtest_multiday.py`
- [x] 4.2 Add `--no-commission` CLI flag (argparse); instantiate `NullCommissionCalculator` when set, else `CommissionCalculator(settings.backtest_commission)`
- [x] 4.3 In `close_position()` and any open-order fill path: compute `commission_inr` via calculator and set on the `Trade` record (`turnover_inr = trade.qty * trade.price`)
- [x] 4.4 In `simulate_day()`: replace crude `charges = sum(...) * 2 * 7.25` with `commission_total = sum(t.commission_inr for t in trades)`; rename `day_pnl` to `gross_pnl` in result dict; keep `realized = gross_pnl - commission_total`
- [x] 4.5 Update `print_day()`: rename "Net premium" label to "Gross premium"; keep charges and realized labels
- [x] 4.6 Update summary table: add `Gross` and `Comm` columns alongside existing `Net`; update footer to show `Total gross`, `Total commission`, `Total net`, `Avg daily net`

## 5. Validation

- [x] 5.1 Run `backtest_multiday.py --days 3` and verify commission totals are non-zero and plausible (₹100–500 per day for a typical straddle day)
- [x] 5.2 Run `backtest_multiday.py --days 3 --no-commission` and verify all commission fields are 0 and gross equals net
- [x] 5.3 Run `pytest tests/backtest/test_commissions.py -v` — all pass
- [x] 5.4 Run `pyright src/pdp/backtest/commissions.py` — no type errors
