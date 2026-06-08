# Backtest Engine

The backtest engine allows you to validate strategies against historical market data using the exact same interface as live trading.

## Quick Start

### Run a backtest

```bash
pdp backtest run my_strategy --from 2024-01-01 --to 2024-12-31
```

Options:
- `--from` (required): Start date in YYYY-MM-DD format
- `--to` (required): End date in YYYY-MM-DD format
- `--initial-equity` (optional): Starting capital (default: 100000)

### List previous backtests

```bash
pdp backtest list
```

Filter by strategy:
```bash
pdp backtest list --strategy-id my_strategy
```

## How It Works

### Event-Driven Replay

The backtest engine replays historical bars through your strategy using the same event-driven interface as live trading:

1. **Load historical bars** from MongoDB `market_bars` collection
2. **Pre-compute indicators** (SMA, EMA, RSI) for the entire date range using Polars vectorization
3. **Process bars chronologically**, calling `on_bar()` hook for each bar
4. **Simulate order execution** at bar close price with no slippage
5. **Track trades and daily P&L**, write results to PostgreSQL
6. **Export CSV files** for analysis in spreadsheet software

### Simulated Time

During backtest, `datetime.now()` returns the current bar's timestamp, not wall-clock time. This ensures date-based logic in your strategy behaves identically to live trading.

Example:
```python
class MyStrategy(Strategy):
    async def on_bar(self, bar: BarClosed) -> None:
        # datetime.now() returns bar.bar_time during backtest
        if datetime.now().weekday() == 4:  # Friday
            # Skip Friday trades
            return
```

### Order Execution Model

- Orders fill **immediately** at the bar close price
- No slippage, partial fills, or intrabar execution
- Orders that exceed position limits or available equity are **rejected**
- Rejections are logged but don't stop the backtest

This is a **conservative baseline**. If you need more sophisticated fill logic, post-process the CSV results.

## Results

Backtest results are stored in three locations:

### 1. PostgreSQL (Persistent)

**Table: `backtest_runs`**
- Strategy ID, date range, start/end equity
- Configuration snapshot (timeframes, initial equity)
- Created timestamp

**Table: `backtest_trades`**
- Each trade: entry/exit price, quantity, P&L
- Entry and exit timestamps
- Strategy metadata

**Table: `backtest_daily`**
- Daily starting/ending equity, daily P&L
- Trade count per day
- Max drawdown and current drawdown %

### 2. CSV Files

Located at `backtest/results/<run_id>/`:

**trades.csv**
```
symbol,quantity,entry_price,entry_time,exit_price,exit_time,realized_pnl,return_pct
NIFTY,100,20000.00,2024-01-01T09:15:00,20100.00,2024-01-02T15:30:00,10000.00,5.00
```

**daily.csv**
```
date,starting_equity,ending_equity,daily_pnl,daily_return_pct,trades_count,max_drawdown,current_drawdown_pct
2024-01-01,100000.00,105000.00,5000.00,5.00,1,0.00,0.00
```

### 3. REST API

Query backtest results programmatically:

```bash
# List backtests
curl http://localhost:8000/api/backtests

# Get backtest details
curl http://localhost:8000/api/backtests/123

# Get trades for a backtest
curl http://localhost:8000/api/backtests/123/trades?limit=100

# Get daily curve
curl http://localhost:8000/api/backtests/123/daily
```

## Indicators

Pre-computed indicators available during backtest:

| Indicator | Period | Type |
|-----------|--------|------|
| SMA | 20, 50 | Simple Moving Average |
| EMA | 12, 26 | Exponential Moving Average |
| RSI | 14 | Relative Strength Index |

Access indicators via the indicator cache in your strategy context (implementation pending).

## Limitations

- **Single-threaded**: Backtests run sequentially, not in parallel
- **Single-timeframe**: Each backtest processes one bar timeframe at a time
- **No slippage**: All fills occur at the bar close price
- **No commissions**: Currently fee-free (configurable in execution model)
- **No portfolio**: Backtests are single-strategy (multi-strategy backtests planned)

## Troubleshooting

### "Strategy 'my_strategy' not found"

Ensure your strategy is registered in the strategy registry and the ID is correct.

### "No bars found for date range"

Check that:
1. Historical bars exist in MongoDB for the requested security and date range
2. Date format is correct (YYYY-MM-DD)
3. You're requesting existing data (e.g., not future dates)

### "Order rejected: insufficient equity"

Your strategy tried to buy more than available cash. Check:
- Initial equity setting
- Trade size relative to equity
- Previous winning/losing trades that reduced available funds

### CSV files not found

CSV export happens automatically after backtest completes. Check:
1. Backtest ran without errors (check run_id in CLI output)
2. `backtest/results/` directory exists
3. Run ID matches the directory name

## Example: Full Backtest Cycle

```bash
# 1. Run a backtest
$ pdp backtest run momentum_strategy --from 2024-01-01 --to 2024-12-31 --initial-equity 100000

Backtest Complete!
Strategy: momentum_strategy
Period: 2024-01-01 to 2024-12-31
Initial Equity: $100,000.00
Final Equity: $125,430.50
Total Return: 25.43%
Total Trades: 42
Run ID: 123
Results: backtest/results/123/

# 2. View results
$ open backtest/results/123/daily.csv  # Open in Excel/Sheets
$ curl http://localhost:8000/api/backtests/123/trades | jq '.trades | length'
42

# 3. List all backtests
$ pdp backtest list --strategy-id momentum_strategy
ID: 123
  Strategy: momentum_strategy
  Period: 2024-01-01 to 2024-12-31
  Return: 25.43%
  Trades: 42
  Created: 2024-06-08T14:30:00
```

## See Also

- [ARCHITECTURE.md#backtest-engine](../ARCHITECTURE.md#backtest-engine) — Technical architecture
- [openspec/specs/backtest/](../openspec/specs/backtest/) — Full requirements specification
