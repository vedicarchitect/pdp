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

    sorted_strikes = sorted(strikes, key=lambda x: x["strike"])
    n = len(sorted_strikes)

    strike_vals = [s["strike"] for s in sorted_strikes]
    ce_ois = [s.get("ce", {}).get("oi", 0) for s in sorted_strikes]
    pe_ois = [s.get("pe", {}).get("oi", 0) for s in sorted_strikes]

    k0 = strike_vals[0]
    pain = 0
    for s, ce_oi in zip(strike_vals, ce_ois, strict=True):
        if s > k0:
            pain += (s - k0) * ce_oi

    min_pain = pain
    max_pain_strike = k0

    pe_oi_sum = pe_ois[0]
    ce_oi_sum = sum(ce_ois[1:])

    for i in range(1, n):
        dk = strike_vals[i] - strike_vals[i - 1]

        pain += dk * pe_oi_sum
        pain -= dk * ce_oi_sum

        if pain < min_pain:
            min_pain = pain
            max_pain_strike = strike_vals[i]

        pe_oi_sum += pe_ois[i]
        ce_oi_sum -= ce_ois[i]

    return int(max_pain_strike)


def compute_pcr(strikes: list[dict]) -> float | None:
    """Return put-call ratio = total put OI / total call OI across all strikes."""
    if not strikes:
        return None
    total_call_oi = sum(s.get("ce", {}).get("oi", 0) for s in strikes)
    total_put_oi = sum(s.get("pe", {}).get("oi", 0) for s in strikes)
    if total_call_oi == 0:
        return None
    return round(total_put_oi / total_call_oi, 4)
