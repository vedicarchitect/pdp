## Why

We need a CLI tool to validate our Dhan integration and portfolio engine implementations are working end-to-end. This tool will help us verify live market data connectivity, position tracking, and options analytics are all functioning correctly during development and testing.

## What Changes

- Add a CLI command to fetch and display current positions from Dhan
- Add a CLI command to fetch and display portfolio summary
- Add a CLI command to fetch the current week's option chain and calculate Greeks (delta, gamma, theta, vega) for open positions
- Provide real-time diagnostics for debugging Dhan broker connectivity and portfolio state

## Capabilities

### New Capabilities
- `progress-test-cli`: CLI tool that queries Dhan positions, portfolio holdings, option chain data, and computes Greeks for positions. Enables developers to validate integration without building full UI.

### Modified Capabilities
<!-- No existing specs are having requirement changes. -->

## Impact

- New CLI entrypoint in the codebase for testing/debugging
- Depends on existing Dhan broker SDK, portfolio engine, and options analytics modules
- Reads market data from configured Dhan account and portfolio state
- No external API or schema changes
