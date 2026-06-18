## Why

PDP has a live option chain feed and analytics (max-pain, GEX, PCR, OI history) but no way to construct, visualize, or evaluate multi-leg option strategies. Platforms like Sensibull and Quantsapp let traders drag legs into a builder, see the payoff curve instantly, evaluate breakevens and max-profit/max-loss, and inspect net Greeks — all before placing a trade. Without a builder, PDP users must calculate payoffs manually or use external tools, breaking the workflow.

## What Changes

- **New backend module `src/pdp/options/payoff.py`**: Pure-function payoff engine — `build_payoff(legs, spot, lot_size, risk_free_rate)` returns: P&L-vs-spot curve (array of `{spot, pnl}` points), breakeven prices, max profit, max loss, net Greeks (delta, gamma, theta, vega summed across legs), probability of profit (lognormal from ATM IV), and a margin estimate (SPAN approximation or rule-based; flagged if exact margin unavailable). Each leg is `{strike, expiry, option_type, side, lots, premium, iv}`.
- **New endpoint `POST /api/v1/options/{underlying}/payoff`**: Accepts legs + current spot, returns payoff analysis.
- **New endpoint `GET /api/v1/options/{underlying}/readymades`**: Returns a list of readymade strategy templates (straddle, strangle, bull call spread, bear put spread, iron condor, iron butterfly, calendar spread, ratio spread — 10 templates total) with their leg definitions relative to ATM strike.
- **New frontend route `/builder`**: Interactive strategy builder — select underlying, pick a readymade or add custom legs, see the payoff chart (recharts area chart), Greeks/breakeven/probability panel, and a "Trade This" button that hands off to the order entry UI (proposal `2026-06-17-virtual-trading-and-alerts-ui`).
- **Option chain integration**: The builder loads the live option chain from `GET /api/v1/options/{underlying}/chain` and lets users click strikes to add legs.

## Capabilities

### New Capabilities
- `options-strategy-builder`: Multi-leg strategy construction, payoff analysis engine, readymade templates, payoff visualization, and "trade this" handoff.

### Modified Capabilities
- `options-analytics`: New `/payoff` and `/readymades` endpoints added under the options router.

## Impact

- `src/pdp/options/payoff.py` — NEW (payoff engine)
- `src/pdp/options/routes.py` — MODIFIED (add payoff + readymades endpoints)
- `tests/options/test_payoff.py` — NEW
- `frontend/src/routes/builder.tsx` — NEW
- `frontend/src/components/builder/BuilderPanel.tsx` — NEW (main builder layout)
- `frontend/src/components/builder/LegTable.tsx` — NEW (editable legs table)
- `frontend/src/components/builder/PayoffChart.tsx` — NEW (recharts area chart)
- `frontend/src/components/builder/GreeksPanel.tsx` — NEW (net Greeks + breakevens + PoP)
- `frontend/src/components/builder/ReadymadeSelector.tsx` — NEW (template picker)
- `frontend/src/components/builder/ChainPicker.tsx` — NEW (click-to-add from option chain)
- `frontend/src/components/Sidebar.tsx` — MODIFIED (add Builder link under OPTIONS)
- No new external Python dependencies (payoff math uses numpy if available, falls back to stdlib math).
- No new npm dependencies.
