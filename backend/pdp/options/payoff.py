import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class PayoffLeg:
    strike: float
    expiry: str
    option_type: Literal["CE", "PE"]
    side: Literal["BUY", "SELL"]
    lots: int
    premium: float
    iv: float
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

@dataclass
class PayoffResult:
    pnl_curve: list[dict]        # [{"spot": float, "pnl": float}, ...]
    breakevens: list[float]
    max_profit: float | None     # None if unlimited
    max_loss: float | None       # None if unlimited
    net_greeks: dict             # {"delta": float, "gamma": float, "theta": float, "vega": float}
    probability_of_profit: float # 0.0-1.0
    margin_estimate: float | None
    margin_is_approximate: bool

READYMADE_STRATEGIES = [
    {
        "name": "Long Straddle",
        "legs": [
            {"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
            {"offset": 0, "type": "PE", "side": "BUY", "lots": 1}
        ]
    },
    {
        "name": "Short Straddle",
        "legs": [
            {"offset": 0, "type": "CE", "side": "SELL", "lots": 1},
            {"offset": 0, "type": "PE", "side": "SELL", "lots": 1}
        ]
    },
    {
        "name": "Long Strangle",
        "legs": [
            {"offset": +1, "type": "CE", "side": "BUY", "lots": 1},
            {"offset": -1, "type": "PE", "side": "BUY", "lots": 1}
        ]
    },
    {
        "name": "Short Strangle",
        "legs": [
            {"offset": +1, "type": "CE", "side": "SELL", "lots": 1},
            {"offset": -1, "type": "PE", "side": "SELL", "lots": 1}
        ]
    },
    {
        "name": "Bull Call Spread",
        "legs": [
            {"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
            {"offset": +2, "type": "CE", "side": "SELL", "lots": 1}
        ]
    },
    {
        "name": "Bear Put Spread",
        "legs": [
            {"offset": 0, "type": "PE", "side": "BUY", "lots": 1},
            {"offset": -2, "type": "PE", "side": "SELL", "lots": 1}
        ]
    },
    {
        "name": "Iron Condor",
        "legs": [
            {"offset": -2, "type": "PE", "side": "BUY", "lots": 1},
            {"offset": -1, "type": "PE", "side": "SELL", "lots": 1},
            {"offset": +1, "type": "CE", "side": "SELL", "lots": 1},
            {"offset": +2, "type": "CE", "side": "BUY", "lots": 1}
        ]
    },
    {
        "name": "Iron Butterfly",
        "legs": [
            {"offset": -1, "type": "PE", "side": "BUY", "lots": 1},
            {"offset": 0, "type": "PE", "side": "SELL", "lots": 1},
            {"offset": 0, "type": "CE", "side": "SELL", "lots": 1},
            {"offset": +1, "type": "CE", "side": "BUY", "lots": 1}
        ]
    },
    {
        "name": "Ratio Spread",
        "legs": [
            {"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
            {"offset": +2, "type": "CE", "side": "SELL", "lots": 2}
        ]
    },
    {
        "name": "Calendar Spread",
        "note": "P&L shown at nearest expiry; actual P&L depends on IV at that time.",
        "legs": [
            {"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
            {"offset": 0, "type": "CE", "side": "SELL", "lots": 1}
        ]
    }
]

def normal_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def build_payoff(
    legs: list[PayoffLeg],
    spot: float,
    lot_size: int,
    risk_free_rate: float = 0.07,
    days_to_expiry: int | None = None,
) -> PayoffResult:
    if not legs:
        return PayoffResult([], [], 0.0, 0.0, {"delta":0,"gamma":0,"theta":0,"vega":0}, 0.0, 0.0, True)

    points = 200
    spot_min = spot * 0.85
    spot_max = spot * 1.15
    if legs:
        min_strike = min(leg.strike for leg in legs)
        max_strike = max(leg.strike for leg in legs)
        spot_min = min(spot_min, min_strike * 0.95)
        spot_max = max(spot_max, max_strike * 1.05)

    step = (spot_max - spot_min) / (points - 1)

    pnl_curve = []
    
    # Calculate P&L for each spot point
    for i in range(points):
        sim_spot = spot_min + i * step
        total_pnl = 0.0
        
        for leg in legs:
            if leg.option_type == "CE":
                intrinsic = max(0.0, sim_spot - leg.strike)
            else:
                intrinsic = max(0.0, leg.strike - sim_spot)
                
            qty = leg.lots * lot_size
            if leg.side == "BUY":
                leg_pnl = (intrinsic - leg.premium) * qty
            else:
                leg_pnl = (leg.premium - intrinsic) * qty
                
            total_pnl += leg_pnl
            
        pnl_curve.append({"spot": round(sim_spot, 2), "pnl": round(total_pnl, 2)})

    # Calculate breakevens (zero crossings)
    breakevens = []
    for i in range(1, points):
        prev = pnl_curve[i-1]
        curr = pnl_curve[i]
        if prev["pnl"] * curr["pnl"] <= 0 and prev["pnl"] != curr["pnl"]:
            # linear interpolation
            m = (curr["pnl"] - prev["pnl"]) / (curr["spot"] - prev["spot"])
            # 0 = m * (x - x1) + y1  => x = -y1/m + x1
            if m != 0:
                zero_spot = -prev["pnl"] / m + prev["spot"]
                breakevens.append(round(zero_spot, 2))

    breakevens = sorted(list(set(breakevens)))

    # Calculate net Greeks
    net_greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        multiplier = 1 if leg.side == "BUY" else -1
        qty = leg.lots * lot_size
        net_greeks["delta"] += leg.delta * qty * multiplier
        net_greeks["gamma"] += leg.gamma * qty * multiplier
        net_greeks["theta"] += leg.theta * qty * multiplier
        net_greeks["vega"] += leg.vega * qty * multiplier

    for k in net_greeks:
        net_greeks[k] = round(net_greeks[k], 4)

    # Determine unbounded max profit/loss
    # Check the slopes at the extreme ends
    p0 = pnl_curve[0]["pnl"]
    p1 = pnl_curve[1]["pnl"]
    pn1 = pnl_curve[-2]["pnl"]
    pn = pnl_curve[-1]["pnl"]

    down_slope = p1 - p0
    up_slope = pn - pn1

    min_pnl = min(p["pnl"] for p in pnl_curve)
    max_pnl = max(p["pnl"] for p in pnl_curve)

    max_loss = min_pnl
    if down_slope > 0.01 or up_slope < -0.01:
        max_loss = None # Unbounded loss
        
    max_profit = max_pnl
    if down_slope < -0.01 or up_slope > 0.01:
        max_profit = None # Unbounded profit

    # Simple probability of profit estimate
    # Log-normal model of stock price
    if not days_to_expiry or days_to_expiry <= 0:
        days_to_expiry = 1
        
    t = days_to_expiry / 365.0
    atm_iv = 0.20
    # Try to find a leg close to ATM to use its IV
    atm_legs = sorted(legs, key=lambda leg: abs(leg.strike - spot))
    if atm_legs and atm_legs[0].iv > 0:
        atm_iv = atm_legs[0].iv

    pop = 0.0
    if pnl_curve[points//2]["pnl"] > 0:
        # Currently in profit. Calculate prob of staying in profit bounded by breakevens.
        if not breakevens:
            pop = 1.0 if max_loss is not None and max_loss >= 0 else 0.5
        elif len(breakevens) == 1:
            be = breakevens[0]
            d2 = (math.log(spot / be) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            prob_above = normal_cdf(d2)
            if be > spot:
                pop = 1.0 - prob_above
            else:
                pop = prob_above
        elif len(breakevens) == 2:
            be1, be2 = breakevens[0], breakevens[1]
            d2_1 = (math.log(spot / be1) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            d2_2 = (math.log(spot / be2) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            prob1 = normal_cdf(d2_1)
            prob2 = normal_cdf(d2_2)
            pop = abs(prob1 - prob2)
    else:
        # Currently at loss.
        if not breakevens:
            pop = 0.0
        elif len(breakevens) == 1:
            be = breakevens[0]
            d2 = (math.log(spot / be) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            prob_above = normal_cdf(d2)
            # If spot is below BE and we need it above
            if pnl_curve[-1]["pnl"] > 0:
                pop = prob_above
            else:
                pop = 1.0 - prob_above
        elif len(breakevens) == 2:
            be1, be2 = breakevens[0], breakevens[1]
            d2_1 = (math.log(spot / be1) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            d2_2 = (math.log(spot / be2) + (risk_free_rate - 0.5 * atm_iv**2) * t) / (atm_iv * math.sqrt(t))
            prob1 = normal_cdf(d2_1)
            prob2 = normal_cdf(d2_2)
            pop = 1.0 - abs(prob1 - prob2)

    # Margin estimate
    # Conservative rule: if max loss bounded, margin is max loss
    # If unbounded, margin is ~15% of spot per naked short lot
    margin_estimate = 0.0
    if max_loss is not None:
        margin_estimate = abs(max_loss)
    else:
        short_lots = sum(leg.lots for leg in legs if leg.side == "SELL")
        margin_estimate = (0.15 * spot * lot_size) * short_lots
        
    # Always include premium paid/received
    net_premium = sum((leg.premium * leg.lots * lot_size * (-1 if leg.side == "BUY" else 1)) for leg in legs)
    if net_premium < 0:
        # Debit spread or long position
        margin_estimate = max(margin_estimate, abs(net_premium))
        
    # Return result
    return PayoffResult(
        pnl_curve=pnl_curve,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        net_greeks=net_greeks,
        probability_of_profit=round(pop, 4),
        margin_estimate=round(margin_estimate, 2),
        margin_is_approximate=True
    )
