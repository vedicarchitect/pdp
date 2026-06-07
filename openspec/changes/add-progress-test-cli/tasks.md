## 1. CLI Infrastructure Setup

- [x] 1.1 Create `cli/` directory structure and main entrypoint (`cli/main.py`)
- [x] 1.2 Set up Click CLI framework with main command group
- [x] 1.3 Add CLI configuration loading (environment variables, config file support)
- [x] 1.4 Implement paper vs. live engine selection based on LIVE env var and broker config

## 2. Positions Command

- [x] 2.1 Create positions subcommand handler
- [x] 2.2 Integrate Dhan SDK to fetch current positions
- [x] 2.3 Format positions data (symbol, quantity, entry price, current price, P&L)
- [x] 2.4 Implement Rich table output for positions display
- [x] 2.5 Add JSON output option (`--format json`) for positions
- [x] 2.6 Add error handling for Dhan connection failures or empty positions

## 3. Portfolio Command

- [x] 3.1 Create portfolio subcommand handler
- [x] 3.2 Integrate portfolio engine to fetch aggregated metrics
- [x] 3.3 Display portfolio summary (invested value, market value, realized P&L, MTM P&L)
- [x] 3.4 Group holdings by asset class (equities, F&O, commodities) in output
- [x] 3.5 Implement Rich table output for portfolio display
- [x] 3.6 Add JSON output option (`--format json`) for portfolio
- [x] 3.7 Add timestamp to portfolio output (fetch time)

## 4. Option Chain Command

- [x] 4.1 Create option-chain subcommand handler
- [x] 4.2 Query Dhan for current week's expiry (nearest weekly)
- [x] 4.3 Fetch option chain data (strike, bid, ask, OI, IV)
- [x] 4.4 Implement `--symbol` filter parameter (default to NIFTY or configured default)
- [x] 4.5 Format and display option chain with calls and puts side-by-side
- [x] 4.6 Implement Rich table output for option chain
- [x] 4.7 Add JSON output option (`--format json`) for option chain
- [x] 4.8 Handle offline/closed market conditions gracefully

## 5. Greeks Calculation

- [x] 5.1 Create greeks subcommand handler
- [x] 5.2 Fetch all open derivative positions from portfolio
- [x] 5.3 Integrate options analytics module to calculate delta, gamma, theta, vega, rho
- [x] 5.4 Use current spot price and IV from option chain for calculations
- [x] 5.5 Handle missing IV for illiquid options (display "N/A" with note)
- [x] 5.6 Format Greeks output (delta, gamma, theta, vega, rho per position)
- [x] 5.7 Implement Rich table output for Greeks display
- [x] 5.8 Add JSON output option (`--format json`) for Greeks
- [x] 5.9 Verify sign convention is correct for long/short positions

## 6. Output Formatting & Polish

- [x] 6.1 Implement Rich table styling and alignment for all commands
- [x] 6.2 Add consistent header formatting and descriptions
- [x] 6.3 Add timestamp formatting utility (market time or local time)
- [x] 6.4 Implement JSON serialization for all data types
- [x] 6.5 Add `--format` flag to all commands (default: table, option: json)
- [x] 6.6 Add help text and usage examples to all subcommands
- [x] 6.7 Implement pretty-print error messages with context

## 7. Integration & Testing

- [x] 7.1 Test `pdp-cli positions` with sample Dhan account
- [x] 7.2 Test `pdp-cli portfolio` with paper engine
- [x] 7.3 Test `pdp-cli option-chain` with NIFTY and custom symbols
- [x] 7.4 Test `pdp-cli greeks` with open derivative positions
- [x] 7.5 Test JSON output format for all commands (`--format json`)
- [x] 7.6 Test error handling (no positions, no portfolio data, API failures)
- [x] 7.7 Test paper vs. live mode switching (LIVE=1 env var)
- [x] 7.8 Verify all output is readable and matches design intent

## 8. Documentation

- [x] 8.1 Add CLI usage documentation to README/DOCS
- [x] 8.2 Document all subcommands, options, and expected output
- [x] 8.3 Add environment variable documentation (LIVE, BROKER_CONFIG, etc.)
- [x] 8.4 Create quick-start example showing typical workflow
