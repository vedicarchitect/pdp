## 1. Backend payoff engine

- [x] 1.1 Create `src/pdp/options/payoff.py` with `PayoffLeg` and `PayoffResult` dataclasses
- [x] 1.2 Implement `build_payoff(legs, spot, lot_size, risk_free_rate, days_to_expiry)` — compute P&L curve at 200 spot points (±15% from spot)
- [x] 1.3 Implement breakeven calculation — find zero-crossings in the P&L curve via linear interpolation
- [x] 1.4 Implement max-profit / max-loss detection — scan P&L curve endpoints and interior; return `None` if unbounded
- [x] 1.5 Implement net Greeks aggregation — sum delta, gamma, theta, vega across all legs
- [x] 1.6 Implement probability-of-profit — lognormal CDF using ATM IV; fallback to `math.erf` if scipy unavailable
- [x] 1.7 Implement margin estimation — rule-based (naked short, spread, straddle rules); set `margin_is_approximate=True`
- [x] 1.8 Define `READYMADE_STRATEGIES` list — straddle, strangle, bull call spread, bear put spread, iron condor, iron butterfly, ratio spread, calendar spread; each with offset-based leg definitions

## 2. Backend endpoints

- [x] 2.1 Add `POST /api/v1/options/{underlying}/payoff` to `src/pdp/options/routes.py` — accepts `{legs: [...], spot: float, lot_size: int}`; calls `build_payoff()`; returns `PayoffResult` as JSON
- [x] 2.2 Add `GET /api/v1/options/{underlying}/readymades` to `src/pdp/options/routes.py` — returns the list of readymade strategy templates
- [x] 2.3 Verify: `task dev` → `curl -X POST http://localhost:8000/api/v1/options/NIFTY/payoff -d '{"legs": [...], "spot": 24850, "lot_size": 75}'` → valid JSON response

## 3. Tests

- [x] 3.1 Create `tests/options/test_payoff.py`
- [x] 3.2 Test long straddle payoff: known breakevens, symmetric P&L curve
- [x] 3.3 Test bull call spread payoff: max profit = strike diff - net debit, max loss = net debit
- [x] 3.4 Test iron condor payoff: bounded profit and loss
- [x] 3.5 Test single leg (naked call buy): max loss = premium, max profit = unlimited (None)
- [x] 3.6 Test probability-of-profit is between 0.0 and 1.0
- [x] 3.7 Test margin estimate is positive for short positions
- [x] 3.8 Run `pytest tests/options/test_payoff.py -v` — all pass

## 4. Frontend builder route

- [x] 4.1 Create `frontend/src/routes/builder.tsx` — `createFileRoute('/builder')` with `BuilderPanel` component
- [x] 4.2 Create `frontend/src/components/builder/BuilderPanel.tsx` — main layout: two-column on desktop, stacked on mobile; underlying selector dropdown
- [x] 4.3 Create `frontend/src/components/builder/ReadymadeSelector.tsx` — grid of readymade template buttons; clicking one populates the legs table from `/readymades` endpoint + current chain data
- [x] 4.4 Create `frontend/src/components/builder/LegTable.tsx` — editable DataTable of legs: Strike, Type (CE/PE toggle), Side (BUY/SELL toggle), Lots (NumberField), Premium (auto-filled from chain, editable), IV. Add Leg / Remove Leg buttons.
- [x] 4.5 Create `frontend/src/components/builder/ChainPicker.tsx` — compact option chain view (from `GET /api/v1/options/{underlying}/chain`); clicking a CE/PE cell adds a leg to LegTable
- [x] 4.6 Create `frontend/src/components/builder/PayoffChart.tsx` — recharts AreaChart showing P&L vs spot; profit zone filled green, loss zone filled red; breakeven markers; zero line
- [x] 4.7 Create `frontend/src/components/builder/GreeksPanel.tsx` — display net delta, gamma, theta, vega, breakevens, max profit, max loss, PoP, margin estimate; use Card + Badge from ui-kit

## 5. Frontend integration

- [x] 5.1 Wire `BuilderPanel` to call `POST /api/v1/options/{underlying}/payoff` whenever legs change (debounced 300ms via TanStack Query)
- [x] 5.2 Add "Trade This" button to `GreeksPanel` — disabled with tooltip "Order entry coming soon" until proposal #6 ships
- [x] 5.3 Add "Builder" link to sidebar under OPTIONS group (icon: `BarChart3` or `TrendingUp` from lucide)
- [x] 5.4 Verify: navigate to `/builder`, select NIFTY, pick "Long Straddle" → payoff chart renders, Greeks panel populates

## 6. Final verification

- [x] 6.1 Run `pytest tests/options/ -v` — all pass
- [x] 6.2 Run `cd frontend && npm run build` — clean build
- [x] 6.3 Run `task lint` — no lint errors on new files
- [x] 6.4 Visual check: builder page renders correctly, payoff chart updates on leg changes, readymade templates populate correctly
