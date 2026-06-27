# Progress Test CLI

A command-line tool for validating Dhan integration, portfolio engine, and options analytics functionality.

## Overview

The progress test CLI provides quick access to verify that core trading infrastructure components are working correctly without standing up the full web server.

## Installation

The CLI is included with the PDP package. After installing dependencies:

```bash
pip install -e .
```

## Usage

### General Format

```bash
pdp progress <command> [--format table|json] [options]
```

### Commands

#### 1. positions

Display current open positions from the portfolio.

```bash
pdp progress positions
pdp progress positions --format json
```

**Output columns:**
- Symbol: Security identifier (e.g., NIFTY23MAR20000CE)
- Segment: Exchange segment (NSE_EQ, NSE_FNO, etc.)
- Product: Product type (NRML, MIS, CNC)
- Qty: Net quantity
- Entry Price: Average entry price
- Current Price: Last known price
- P&L: Unrealized P&L
- Updated: Last update timestamp

**Example:**
```
$ pdp progress positions
Current Positions
┌─────────────────────┬─────────────┬─────────┬────┬──────────┬───────────┬───────┬──────────────┐
│ Symbol              │ Segment     │ Product │ Qty│ Entry Pr │ Current Pr│  P&L  │   Updated    │
├─────────────────────┼─────────────┼─────────┼────┼──────────┼───────────┼───────┼──────────────┤
│ NIFTY23MAR20000CE   │ NSE_FNO     │ NRML    │ 1  │  123.45  │  123.45   │ -5.67 │ 2024-06-07T1 │
│ SBIN-EQ             │ NSE_EQ      │ CNC     │ 10 │  456.78  │  456.78   │ 45.60 │ 2024-06-07T1 │
└─────────────────────┴─────────────┴─────────┴────┴──────────┴───────────┴───────┴──────────────┘
```

#### 2. portfolio

Display aggregated portfolio metrics and breakdown by asset class.

```bash
pdp progress portfolio
pdp progress portfolio --format json
```

**Metrics displayed:**
- Mode: Paper or Live trading mode
- Total Unrealized P&L: MTM P&L of open positions
- Total Realized P&L: Closed trades P&L
- Total P&L: Sum of realized + unrealized
- Open Positions: Count of positions with non-zero quantity
- By Segment: Breakdown of positions and P&L by exchange segment

**Example:**
```
$ pdp progress portfolio
Portfolio Summary
┌────────────────────────┬──────────────┐
│ Metric                 │ Value        │
├────────────────────────┼──────────────┤
│ Mode                   │ paper        │
│ Total Unrealized P&L   │ 39.93        │
│ Total Realized P&L     │ 0.00         │
│ Total P&L              │ 39.93        │
│ Open Positions         │ 2            │
│ Timestamp              │ 2024-06-07T1 │
└────────────────────────┴──────────────┘

By Segment
┌─────────────┬───────────┬────────────────┬───────────────┐
│ Segment     │ Positions │ Unrealized P&L │ Realized P&L  │
├─────────────┼───────────┼────────────────┼───────────────┤
│ NSE_EQ      │ 1         │ 45.60          │ 0.00          │
│ NSE_FNO     │ 1         │ -5.67          │ 0.00          │
└─────────────┴───────────┴────────────────┴───────────────┘
```

#### 3. option-chain

Fetch and display the current week's option chain with bid/ask/OI/IV.

```bash
pdp progress option-chain
pdp progress option-chain --symbol BANKNIFTY
pdp progress option-chain --symbol NIFTY --format json
```

**Options:**
- `--symbol`: Filter by underlying (default: NIFTY)
- `--format`: Output format (default: table, options: json)

**Output columns:**
- Strike: Strike price
- Call Bid/Ask: Call option bid/ask prices
- Call OI: Call open interest
- Call IV: Call implied volatility
- Put Bid/Ask: Put option bid/ask prices
- Put OI: Put open interest
- Put IV: Put implied volatility

**Example:**
```
$ pdp progress option-chain --symbol NIFTY
NIFTY Option Chain - 2024-06-07T14:30:45.123456
┌────────┬──────┬──────┬────┬────┬──────┬──────┬────┬────┐
│ Strike │ C Bid│ C Ask│C OI│C IV│ P Bid│ P Ask│P OI│P IV│
├────────┼──────┼──────┼────┼────┼──────┼──────┼────┼────┤
│ 19500  │ 500  │ 510  │ 15 │0.25│ 5.50 │ 6.00 │200 │0.30│
│ 20000  │ 300  │ 310  │ 50 │0.22│ 12.5 │ 13.5 │500 │0.28│
│ 20500  │ 150  │ 160  │100 │0.20│ 35.0 │ 36.0 │150 │0.26│
└────────┴──────┴──────┴────┴────┴──────┴──────┴────┴────┘
```

#### 4. greeks

Calculate and display Greeks (delta, gamma, theta, vega) for open derivative positions.

```bash
pdp progress greeks
pdp progress greeks --format json
```

**Output columns:**
- Symbol: Option security identifier
- Qty: Position quantity
- Avg Price: Average entry price
- Delta: Option delta (sensitivity to spot price change)
- Gamma: Rate of change of delta
- Theta: Time decay (daily)
- Vega: IV sensitivity (per 1% change)
- IV: Implied volatility

**Greeks interpretation:**
- **Delta**: 0 to 1 for calls (0 to -1 for puts)
  - 0.5 = ATM, ~50% probability ITM
  - Short positions: negate the delta
- **Gamma**: Convexity of option, highest at ATM
- **Theta**: Daily time decay in rupees (negative = time decay loss for long)
- **Vega**: P&L sensitivity per 1% increase in IV

**Example:**
```
$ pdp progress greeks
Greeks for Open Positions
┌──────────────────┬─────┬──────────┬───────┬──────┬───────┬──────┬──────┐
│ Symbol           │ Qty │ Avg Pric │ Delta │ Gam  │ Theta │ Vega │  IV  │
├──────────────────┼─────┼──────────┼───────┼──────┼───────┼──────┼──────┤
│ NIFTY23MAR20000CE│ 1   │ 123.45   │ 0.45  │ 0.01 │ -0.20 │ 45.5 │ 0.25 │
│ BANKNIFTY23JUL430│ 1   │ 456.78   │ 0.62  │ 0.02 │ -0.15 │ 67.8 │ 0.22 │
└──────────────────┴─────┴──────────┴───────┴──────┴───────┴──────┴──────┘
```

## Output Formats

### Table (default)

Human-readable ASCII tables with aligned columns. Best for manual inspection.

```bash
pdp progress positions
pdp progress positions --format table  # explicit
```

### JSON

Machine-readable JSON output. Suitable for scripting and automation.

```bash
pdp progress positions --format json
```

All commands produce JSON with:
- `timestamp`: When data was fetched (ISO 8601)
- `count`: Number of items returned (where applicable)
- `<data>`: The main payload (positions array, portfolio summary, etc.)

**Example:**
```json
{
  "timestamp": "2024-06-07T14:30:45.123456",
  "count": 2,
  "positions": [
    {
      "security_id": "NIFTY23MAR20000CE",
      "exchange_segment": "NSE_FNO",
      "product": "NRML",
      "net_qty": 1,
      "avg_price": 123.45,
      "unrealized_pnl": -5.67,
      "updated_at": "2024-06-07T14:30:00"
    }
  ]
}
```

## Environment Variables

### LIVE (default: 0)

Control paper vs. live trading mode.

```bash
# Paper trading (default, safe)
pdp progress positions

# Live trading (requires DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN set)
LIVE=1 pdp progress positions
```

### DEFAULT_SYMBOL (default: NIFTY)

Default symbol for option-chain command.

```bash
DEFAULT_SYMBOL=BANKNIFTY pdp progress option-chain
```

### Database Configuration

The CLI uses the same database configuration as the main app:
- `DATABASE_URL`: PostgreSQL connection string
- See `.env` and `settings.py` for full configuration

## Error Handling

The CLI provides clear error messages for common issues:

- **No positions found**: "No positions found" (not an error)
- **Database connection**: Error message with retry guidance
- **Dhan API failure**: "Failed to fetch option chain: <reason>" with detailed logging
- **Missing IV data**: Greeks display as "N/A" with note about illiquidity

All errors are logged to structlog with context for debugging.

## Typical Workflows

### Pre-trading validation (morning)

```bash
# Check if all systems are working
pdp progress portfolio                 # Overall health
pdp progress positions                 # Existing positions
pdp progress option-chain --symbol NIFTY  # Live market check
```

### Greeks monitoring

```bash
# Check Greeks for open derivative positions
pdp progress greeks

# Export to CSV for analysis
pdp progress greeks --format json | jq '.' > greeks_$(date +%s).json
```

### Troubleshooting

```bash
# JSON format helps with debugging
pdp progress positions --format json  # Full details

# Check paper engine state (default)
pdp progress portfolio

# Check if live account is accessible (when LIVE=1 is set)
LIVE=1 pdp progress positions
```

## Implementation Notes

- All commands are stateless one-shot queries
- Commands respect the LIVE env var for paper vs. live trading
- Greeks calculation uses Black-Scholes-Merton model with vollib
- Option chain is fetched fresh from Dhan on each invocation
- Portfolio data is read from PostgreSQL database

## Troubleshooting

### Command not found: pdp progress

Ensure the package is installed:
```bash
pip install -e .
```

### Database connection error

Check environment variables:
```bash
echo $DATABASE_URL
cat .env | grep DATABASE
```

### No Dhan credentials

For option-chain command, set credentials:
```bash
export DHAN_CLIENT_ID=your_client_id
export DHAN_ACCESS_TOKEN=your_access_token
```

Or set LIVE=1:
```bash
LIVE=1 pdp progress option-chain --symbol NIFTY
```

## See Also

- Main CLI: `pdp serve` (start web server)
- Instruments: `pdp instruments refresh` (load market data)
