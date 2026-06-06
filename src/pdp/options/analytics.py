"""Max-pain and PCR computation from OI data."""
from __future__ import annotations


def compute_max_pain(strikes: list[dict]) -> int | None:
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


def compute_pcr(strikes: list[dict]) -> float | None:
    """Return put-call ratio = total put OI / total call OI across all strikes."""
    if not strikes:
        return None
    total_call_oi = sum(s.get("ce", {}).get("oi", 0) for s in strikes)
    total_put_oi = sum(s.get("pe", {}).get("oi", 0) for s in strikes)
    if total_call_oi == 0:
        return None
    return round(total_put_oi / total_call_oi, 4)
