## Context

PDP's options module (`src/pdp/options/`) currently provides:
- `analytics.py` — max-pain, PCR, GEX, OI history calculations
- `routes.py` — endpoints for chain, max-pain, pcr, gex, oi-history, refresh
- Options chain data stored in MongoDB (`option_chains` collection)

The existing chain endpoint returns strikes with CE/PE premiums, Greeks, and OI. The payoff engine needs to consume this data to build P&L curves.

There is no payoff calculation anywhere in the codebase today. Black-Scholes Greeks are computed by the chain poller (`OptionsChainPoller`) and stored in MongoDB snapshots, but not used for payoff analysis.

## Goals / Non-Goals

**Goals:**
- Build a pure-function payoff engine with no side effects (testable without DB).
- Support arbitrary multi-leg combinations (2–8 legs typical).
- Provide readymade templates for common strategies that auto-populate legs from the live chain.
- Deliver a frontend builder that rivals Sensibull's visual quality.
- Enable "trade this" handoff to the order entry UI (proposal #6).

**Non-Goals:**
- Real-time payoff updates as spot moves (future enhancement; this version computes on-demand).
- Exact SPAN margin calculation (use SPAN approximation or rule-based estimate; flag as approximate).
- Options strategy backtesting (that is proposal #4).
- Greeks sensitivity analysis (delta/gamma/vega charts vs spot) — future enhancement.

## Decisions

### D1: Payoff engine as pure functions in `payoff.py`

The payoff engine is stateless — it receives legs, spot, lot size, and returns analysis. No DB access, no Redis, no side effects. This makes it trivially testable and reusable by both the API endpoint and the backtester (proposal #4).

```python
@dataclass
class PayoffLeg:
    strike: float
    expiry: date
    option_type: Literal["CE", "PE"]
    side: Literal["BUY", "SELL"]
    lots: int
    premium: float
    iv: float  # implied volatility (annualized, decimal)

@dataclass
class PayoffResult:
    pnl_curve: list[dict]        # [{spot: float, pnl: float}, ...]
    breakevens: list[float]
    max_profit: float | None     # None if unlimited
    max_loss: float | None       # None if unlimited
    net_greeks: dict             # {delta, gamma, theta, vega}
    probability_of_profit: float # 0.0–1.0
    margin_estimate: float | None
    margin_is_approximate: bool

def build_payoff(
    legs: list[PayoffLeg],
    spot: float,
    lot_size: int,
    risk_free_rate: float = 0.07,
    days_to_expiry: int | None = None,
) -> PayoffResult: ...
```

### D2: P&L curve computed at 200 spot points

The P&L curve is computed at 200 evenly-spaced spot points from `spot × 0.85` to `spot × 1.15` (±15% range). Each point calculates the intrinsic payoff at expiry for each leg, sums, and subtracts total premium paid/received. This gives a smooth curve for recharts.

### D3: Probability of profit uses lognormal model

Probability of profit is estimated using the lognormal distribution with ATM IV as the volatility input and the risk-free rate. This is a rough estimate — not a full Monte Carlo simulation — but matches what Sensibull and Quantsapp show.

```python
from scipy.stats import lognorm  # or manual implementation
# P(spot > breakeven at expiry) for net-credit strategies
# P(spot in profit zone) for bounded strategies
```

If scipy is not available, fall back to a normal approximation using the stdlib `math.erf`.

### D4: Margin estimation is rule-based, flagged as approximate

Exact SPAN margin requires exchange-specific calculations. Instead, use a simplified rule:
- Naked short option: `max(premium × 2, spot × 0.05) × lots × lot_size`
- Spread: `|strike_diff| × lots × lot_size - net_credit`
- Straddle/Strangle: `max(CE_margin, PE_margin) + other_premium`

The response includes `margin_is_approximate: true` so the frontend can display "≈" prefix.

### D5: Readymade templates are code-defined, not DB-stored

Templates are a static list in `payoff.py`:

```python
READYMADE_STRATEGIES = [
    {"name": "Long Straddle", "legs": [{"offset": 0, "type": "CE", "side": "BUY"}, {"offset": 0, "type": "PE", "side": "BUY"}]},
    {"name": "Short Straddle", "legs": [...]},
    {"name": "Bull Call Spread", "legs": [{"offset": 0, "type": "CE", "side": "BUY"}, {"offset": +2, "type": "CE", "side": "SELL"}]},
    # ... iron condor, iron butterfly, ratio spread, calendar spread
]
```

`offset` is in strike steps from ATM (0 = ATM, +1 = 1 strike OTM for CE / ITM for PE, etc.).

### D6: Frontend builder layout

```
┌─────────────────────────────────────────────────────┐
│ Strategy Builder — NIFTY (24,850)  [▼ Underlying]   │
├────────────────────────┬────────────────────────────┤
│ Readymade Templates    │  Payoff Chart              │
│ [Straddle] [Strangle]  │  ┌────────────────────────┐│
│ [Bull Call] [Bear Put]  │  │    area chart           ││
│ [Iron Condor] [Custom]  │  │    (recharts)           ││
│                        │  └────────────────────────┘│
├────────────────────────┤  Greeks & Analysis         │
│ Legs Table             │  Delta: +0.12              │
│ ┌──────────────────┐   │  Gamma: 0.003              │
│ │Strike|Type|Side|Lots│  │  Theta: -152              │
│ │24800 |CE  |BUY |1  │  │  Vega:  +45               │
│ │24900 |PE  |SELL|1  │  │  Breakevens: 24,650 / 25,050│
│ │ [+ Add Leg]       │  │  Max Profit: ₹12,350       │
│ └──────────────────┘   │  Max Loss: Unlimited       │
│                        │  PoP: 34.2%                │
│ Option Chain (click    │  Margin: ≈₹1,45,000        │
│ to add leg)            │  [Trade This →]            │
└────────────────────────┴────────────────────────────┘
```

## Risks / Trade-offs

- **scipy dependency**: The probability-of-profit calculation ideally uses `scipy.stats.lognorm`. If scipy is not in the dependency tree, implement a manual CDF using `math.erf`. Check `pyproject.toml` before deciding.
- **Multi-expiry legs**: Calendar spreads have legs with different expiries, which complicates the P&L curve (can't just compute intrinsic at one expiry). For v1, compute payoff at the nearest expiry and flag multi-expiry strategies with a note: "P&L shown at nearest expiry; actual P&L depends on IV at that time."
- **"Trade This" handoff**: This button will be non-functional until proposal #6 (virtual-trading-and-alerts-ui) ships. Render as disabled with a tooltip: "Order entry coming soon."

## Migration Plan

1. Create `src/pdp/options/payoff.py` with `build_payoff()` and `READYMADE_STRATEGIES`.
2. Add `/payoff` and `/readymades` endpoints to `src/pdp/options/routes.py`.
3. Write tests in `tests/options/test_payoff.py` — test each readymade, custom legs, edge cases (single leg, all-buy, all-sell).
4. Build frontend `/builder` route and components.
5. Add Builder link to sidebar.

## Open Questions

- None — payoff math is well-defined and the chain endpoint already provides all required inputs (strike, premium, IV, Greeks).
