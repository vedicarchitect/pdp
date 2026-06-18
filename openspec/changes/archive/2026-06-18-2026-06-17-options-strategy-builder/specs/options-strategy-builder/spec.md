## ADDED Requirements

### Requirement: Payoff analysis engine

The system SHALL provide a `build_payoff()` function that accepts a list of option legs (each with strike, expiry, option_type, side, lots, premium, IV), a spot price, and a lot size, and returns: a P&L-vs-spot curve (200 points spanning ±15% from spot), breakeven prices, max profit (or `None` if unlimited), max loss (or `None` if unlimited), net Greeks (delta, gamma, theta, vega summed across legs), probability of profit (lognormal estimate from ATM IV), and a margin estimate (flagged as approximate).

#### Scenario: Long straddle payoff
- **WHEN** `build_payoff` is called with a long straddle (BUY CE + BUY PE at same strike) with premiums of ₹200 CE and ₹180 PE
- **THEN** the result contains two breakevens (strike ± total premium), max loss = total premium × lots × lot_size, and max profit = `None` (unlimited)

#### Scenario: Bull call spread payoff
- **WHEN** `build_payoff` is called with BUY CE at 24800 (₹250) + SELL CE at 25000 (₹150)
- **THEN** max profit = (25000 - 24800 - net_debit) × lots × lot_size, max loss = net_debit × lots × lot_size, one breakeven between the strikes

#### Scenario: Iron condor payoff
- **WHEN** `build_payoff` is called with 4 legs forming an iron condor
- **THEN** max profit = net credit × lots × lot_size, max loss is bounded, and two breakeven prices exist

---

### Requirement: Payoff REST endpoint

The system SHALL expose `POST /api/v1/options/{underlying}/payoff` accepting a JSON body with `legs`, `spot`, and `lot_size`. The endpoint SHALL return the `PayoffResult` as JSON. Invalid input (e.g., zero legs, missing fields) SHALL return HTTP 422 with a descriptive error.

#### Scenario: Valid payoff request
- **WHEN** `POST /api/v1/options/NIFTY/payoff` is called with valid legs and spot
- **THEN** HTTP 200 is returned with pnl_curve, breakevens, max_profit, max_loss, net_greeks, probability_of_profit, and margin_estimate

#### Scenario: Empty legs returns 422
- **WHEN** `POST /api/v1/options/NIFTY/payoff` is called with an empty legs array
- **THEN** HTTP 422 is returned with error "At least one leg is required"

---

### Requirement: Readymade strategy templates

The system SHALL expose `GET /api/v1/options/{underlying}/readymades` returning a list of readymade strategy templates including at minimum: Long Straddle, Short Straddle, Long Strangle, Short Strangle, Bull Call Spread, Bear Put Spread, Iron Condor, Iron Butterfly, Calendar Spread (same strike, two expiries), and Ratio Spread (1:2 buy/sell). Each template SHALL define legs as offsets from ATM strike.

#### Scenario: List readymade templates
- **WHEN** `GET /api/v1/options/NIFTY/readymades` is called
- **THEN** HTTP 200 is returned with at least 10 strategy templates, each containing `name` and `legs` fields

---

### Requirement: Strategy builder frontend

The system SHALL provide a `/builder` route with: an underlying selector, readymade template buttons, an editable legs table, an option chain picker (click-to-add), a payoff chart (P&L vs spot with profit/loss zone coloring), and a Greeks/analysis panel showing net delta, gamma, theta, vega, breakevens, max profit, max loss, probability of profit, and approximate margin.

#### Scenario: Readymade template populates builder
- **WHEN** a user selects "Long Straddle" from readymade templates
- **THEN** the legs table is populated with 2 legs (BUY CE + BUY PE at ATM strike), and the payoff chart updates

#### Scenario: Click option chain to add leg
- **WHEN** a user clicks the 24900 CE cell in the option chain picker
- **THEN** a new BUY CE leg at strike 24900 is added to the legs table with premium auto-filled from the chain

#### Scenario: Payoff chart updates on leg change
- **WHEN** a user modifies a leg's lots from 1 to 2
- **THEN** the payoff chart re-renders within 500ms with the updated P&L curve

#### Scenario: Trade This button handoff
- **WHEN** the user clicks "Trade This" and proposal #6 is implemented
- **THEN** the legs are passed to the order entry UI pre-populated
