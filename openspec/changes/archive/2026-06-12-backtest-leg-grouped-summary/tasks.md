## 1. Leg accumulation

- [x] 1.1 In `simulate_day`/`close_position`, record a per-leg record on each close: option type, strike, entry IST, exit IST, avg entry, exit price, lots, leg P&L, reason
- [x] 1.2 Ensure scale-ins fold into the parent leg's average entry and lot count

## 2. Summary table

- [x] 2.1 Add a leg-grouped table to `print_day` rendered after the per-order detail
- [x] 2.2 Columns: #, Type, Strike, Entry IST, Exit IST, Lots, Avg Entry, Exit ₹, Leg P&L, Reason
- [x] 2.3 Footer row: leg count, total realized, win/loss legs

## 3. Validation

- [x] 3.1 `openspec validate backtest-leg-grouped-summary --strict`
- [x] 3.2 Run one day; confirm leg P&L sums equal the existing per-order realized total
