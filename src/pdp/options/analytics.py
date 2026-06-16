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

    GEX(K) = (ce_gamma × ce_oi - pe_gamma × pe_oi) × lot_size × spot²
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
