"""Max-pain, PCR, and GEX computation from OI data."""
from __future__ import annotations

from typing import Any


def compute_max_pain(strikes: list[dict[str, Any]]) -> int | None:
    """Return the strike at which total option-writer pain is minimised.

    Pain at a candidate strike K = sum over all strikes S of:
      CE writers: max(0, S - K) * CE_OI(S)
      PE writers: max(0, K - S) * PE_OI(S)
    """
    if not strikes:
        return None

    candidate_strikes = [s["strike"] for s in strikes]
    ce_oi = {s["strike"]: s.get("ce", {}).get("oi", 0) for s in strikes}
    pe_oi = {s["strike"]: s.get("pe", {}).get("oi", 0) for s in strikes}

    min_pain = None
    max_pain_strike = None
    for k in candidate_strikes:
        pain = sum(max(0, s - k) * ce_oi.get(s, 0) for s in candidate_strikes) + sum(
            max(0, k - s) * pe_oi.get(s, 0) for s in candidate_strikes
        )
        if min_pain is None or pain < min_pain:
            min_pain = pain
            max_pain_strike = k
    return int(max_pain_strike) if max_pain_strike is not None else None


def compute_pcr(strikes: list[dict[str, Any]]) -> float | None:
    """Return put-call ratio = total put OI / total call OI across all strikes."""
    if not strikes:
        return None
    total_call_oi = sum(s.get("ce", {}).get("oi", 0) for s in strikes)
    total_put_oi = sum(s.get("pe", {}).get("oi", 0) for s in strikes)
    if total_call_oi == 0:
        return None
    return round(total_put_oi / total_call_oi, 4)


def compute_gex(strikes: list[dict[str, Any]], lot_size: int, spot: float) -> dict[str, Any]:
    """Return net dealer GEX per strike and aggregate.

    GEX(K) = (ce_gamma * ce_oi - pe_gamma * pe_oi) * lot_size * spot^2
    Missing gamma fields default to 0 (no KeyError).
    """
    per_strike: list[dict[str, Any]] = []
    for s in strikes:
        ce = s.get("ce", {})
        pe = s.get("pe", {})
        ce_gamma: float = ce.get("gamma") or 0.0
        pe_gamma: float = pe.get("gamma") or 0.0
        ce_oi: int = ce.get("oi") or 0
        pe_oi: int = pe.get("oi") or 0
        gex = (ce_gamma * ce_oi - pe_gamma * pe_oi) * lot_size * spot ** 2
        per_strike.append({"strike": int(s["strike"]), "gex": gex})
    net_gex: float = sum(float(item["gex"]) for item in per_strike)
    return {"per_strike": per_strike, "net_gex": net_gex}


def classify_oi_buildup(
    current_strikes: list[dict[str, Any]],
    previous_strikes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prev_map = {s["strike"]: s for s in previous_strikes}
    results = []

    def classify(c_opt: dict[str, Any] | None, p_opt: dict[str, Any] | None) -> dict[str, Any] | None:
        if not c_opt or not p_opt:
            return None
        c_price = c_opt.get("last_price") or 0.0
        p_price = p_opt.get("last_price") or 0.0
        c_oi = c_opt.get("oi") or 0
        p_oi = p_opt.get("oi") or 0

        price_change = c_price - p_price
        oi_change = c_oi - p_oi
        oi_change_pct = (oi_change / p_oi * 100) if p_oi > 0 else 0.0

        classification = "neutral"
        if price_change > 0 and oi_change > 0:
            classification = "long_buildup"
        elif price_change < 0 and oi_change > 0:
            classification = "short_buildup"
        elif price_change > 0 and oi_change < 0:
            classification = "short_covering"
        elif price_change < 0 and oi_change < 0:
            classification = "long_unwinding"
            
        return {
            "classification": classification,
            "price_change": round(price_change, 2),
            "oi_change": oi_change,
            "oi_change_pct": round(oi_change_pct, 2)
        }

    for cur in current_strikes:
        strike = cur["strike"]
        prev = prev_map.get(strike)
        if not prev:
            continue
        results.append({
            "strike": strike,
            "ce": classify(cur.get("ce"), prev.get("ce")),
            "pe": classify(cur.get("pe"), prev.get("pe"))
        })
    return results


def compute_straddle_history(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute ATM straddle premium for each snapshot."""
    history = []
    for snap in snapshots:
        spot = snap.get("spot_price") or 0.0
        strikes = snap.get("strikes") or []
        if not strikes or spot == 0.0:
            continue
            
        # Find ATM strike
        atm_strike = min(strikes, key=lambda s: abs(s["strike"] - spot))
        
        ce_price = atm_strike.get("ce", {}).get("last_price") or 0.0
        pe_price = atm_strike.get("pe", {}).get("last_price") or 0.0
        
        history.append({
            "timestamp": snap.get("snapshot_ts"),
            "spot": spot,
            "atm_strike": atm_strike["strike"],
            "ce_premium": ce_price,
            "pe_premium": pe_price,
            "straddle_premium": ce_price + pe_price
        })
    return history


_IV_MIN_DAYS = 20


def compute_iv_rank_percentile(historical_ivs: list[float], current_iv: float) -> dict[str, Any]:
    """Compute IV Rank and IV Percentile from historical IV array."""
    valid_ivs = [iv for iv in historical_ivs if iv is not None and iv > 0]
    if len(valid_ivs) < _IV_MIN_DAYS:
        return {
            "current_iv": round(current_iv, 2),
            "iv_rank": None,
            "iv_percentile": None,
            "iv_high": None,
            "iv_low": None,
            "lookback_days": len(valid_ivs),
            "warning": f"Insufficient historical data: {len(valid_ivs)} days (need {_IV_MIN_DAYS})",
        }

    iv_high = max(valid_ivs)
    iv_low = min(valid_ivs)

    if iv_high == iv_low:
        iv_rank = 0.0
    else:
        iv_rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100

    days_below = sum(1 for iv in valid_ivs if iv < current_iv)
    iv_percentile = (days_below / len(valid_ivs)) * 100

    return {
        "current_iv": round(current_iv, 2),
        "iv_rank": round(iv_rank, 2),
        "iv_percentile": round(iv_percentile, 2),
        "iv_high": round(iv_high, 2),
        "iv_low": round(iv_low, 2),
        "lookback_days": len(valid_ivs),
    }


def multi_strike_oi_series(snapshots: list[dict[str, Any]], top_n: int = 10) -> dict[str, Any]:
    """Compute OI change over time for top N strikes."""
    if not snapshots:
        return {"timestamps": [], "strikes": {}}
        
    latest_strikes = snapshots[-1].get("strikes") or []
    sorted_strikes = sorted(
        latest_strikes,
        key=lambda s: (s.get("ce", {}).get("oi", 0) + s.get("pe", {}).get("oi", 0)),
        reverse=True,
    )
    top_strikes = [s["strike"] for s in sorted_strikes[:top_n]]
    
    timestamps = []
    series_data = {strike: {"ce_oi": [], "pe_oi": []} for strike in top_strikes}
    
    for snap in snapshots:
        ts = snap.get("snapshot_ts")
        timestamps.append(ts)
        strike_map = {s["strike"]: s for s in (snap.get("strikes") or [])}
        
        for strike in top_strikes:
            s_data = strike_map.get(strike)
            if s_data:
                series_data[strike]["ce_oi"].append(s_data.get("ce", {}).get("oi", 0))
                series_data[strike]["pe_oi"].append(s_data.get("pe", {}).get("oi", 0))
            else:
                series_data[strike]["ce_oi"].append(0)
                series_data[strike]["pe_oi"].append(0)
                
    return {
        "timestamps": timestamps,
        "strikes": series_data
    }

