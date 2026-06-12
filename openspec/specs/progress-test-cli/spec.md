# progress-test-cli

## Requirements

### Requirement: CLI displays Dhan positions
The CLI SHALL connect to the Dhan broker SDK and fetch all current positions (stocks, F&O, commodities) from the configured account.

#### Scenario: Display equity positions
- **WHEN** user runs `pdp-cli positions`
- **THEN** system displays a table with symbol, quantity, entry price, current price, and P&L for each equity position

#### Scenario: Display derivatives positions
- **WHEN** user runs `pdp-cli positions`
- **THEN** system displays F&O positions with symbol, lot size, entry price, current price, and Greeks (delta for display)

#### Scenario: Handle no positions
- **WHEN** user runs `pdp-cli positions` with no open positions
- **THEN** system displays "No positions found" message

### Requirement: CLI displays portfolio summary
The CLI SHALL query the portfolio engine and display aggregated portfolio metrics.

#### Scenario: Show portfolio overview
- **WHEN** user runs `pdp-cli portfolio`
- **THEN** system displays total invested value, current market value, realized P&L, and unrealized MTM P&L

#### Scenario: Show portfolio by segment
- **WHEN** user runs `pdp-cli portfolio`
- **THEN** system groups holdings by asset class (equities, F&O, commodities) and shows segment-level metrics

#### Scenario: Portfolio reflects paper engine state
- **WHEN** LIVE=0 (default) and user runs `pdp-cli portfolio`
- **THEN** system displays paper trading portfolio, not live account

### Requirement: CLI fetches and displays option chain
The CLI SHALL fetch the current week's option chain (nearest weekly expiry) from Dhan and display strike prices, bid/ask, open interest, and IV.

#### Scenario: Fetch weekly option chain
- **WHEN** user runs `pdp-cli option-chain`
- **THEN** system displays all call and put strikes for the current week's expiry, with strike, bid, ask, open interest, and implied volatility

#### Scenario: Filter by underlying symbol
- **WHEN** user runs `pdp-cli option-chain --symbol NIFTY`
- **THEN** system displays option chain for NIFTY only (default filters to most liquid index or configured default)

#### Scenario: Handle no option chain data
- **WHEN** user runs `pdp-cli option-chain` and market is closed
- **THEN** system displays last available option chain data with a timestamp

### Requirement: CLI calculates and displays Greeks for open positions
The CLI SHALL compute Greeks (delta, gamma, theta, vega) for all open derivative positions and display them alongside positions.

#### Scenario: Calculate Greeks for short options
- **WHEN** user runs `pdp-cli greeks` with open short call/put positions
- **THEN** system displays delta, gamma, theta, vega, rho for each position using spot price from current market data

#### Scenario: Greeks reflect current market price
- **WHEN** option spot price has changed since position entry
- **THEN** Greeks are recalculated using current spot and IV from option chain

#### Scenario: Handle missing IV for illiquid options
- **WHEN** IV is unavailable for an option (illiquid strike)
- **THEN** system displays "N/A" for Greeks with a note about illiquidity; does not error

#### Scenario: Greeks for long positions are signed correctly
- **WHEN** user has long call and short put positions
- **THEN** delta is positive for calls, negative for puts; sign convention is correct for Greeks calculations

### Requirement: CLI output is formatted for easy reading
The CLI SHALL format all output as readable tables with proper alignment and optional JSON export.

#### Scenario: Default human-readable output
- **WHEN** user runs any CLI command
- **THEN** system displays results as aligned ASCII tables with headers and column labels

#### Scenario: JSON output mode
- **WHEN** user runs `pdp-cli positions --format json`
- **THEN** system outputs valid JSON with array of position objects (suitable for scripting/automation)

#### Scenario: Timestamps are included
- **WHEN** user runs any CLI command
- **THEN** output includes timestamp of when data was fetched (market time or system time as appropriate)
