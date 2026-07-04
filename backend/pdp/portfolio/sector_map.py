"""Static NSE/BSE symbol -> sector lookup for holdings allocation advice.

Covers common large/mid-cap symbols. Unmapped symbols fall back to "Other" rather
than blocking advisory computation on a missing classification.
"""
from __future__ import annotations

_SECTOR_BY_SYMBOL: dict[str, str] = {
    "TCS": "Technology", "INFY": "Technology", "WIPRO": "Technology",
    "HCLTECH": "Technology", "TECHM": "Technology", "LTIM": "Technology",
    "HDFCBANK": "Financials", "ICICIBANK": "Financials", "SBIN": "Financials",
    "KOTAKBANK": "Financials", "AXISBANK": "Financials", "BAJFINANCE": "Financials",
    "INDUSINDBK": "Financials", "HDFCLIFE": "Financials", "SBILIFE": "Financials",
    "SUNPHARMA": "Healthcare", "DRREDDY": "Healthcare", "CIPLA": "Healthcare",
    "DIVISLAB": "Healthcare", "APOLLOHOSP": "Healthcare",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "NTPC": "Energy",
    "POWERGRID": "Energy",
    "ITC": "Consumer", "HINDUNILVR": "Consumer", "NESTLEIND": "Consumer",
    "TITAN": "Consumer", "ASIANPAINT": "Consumer", "BRITANNIA": "Consumer",
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto", "HEROMOTOCO": "Auto",
    "TATASTEEL": "Materials", "JSWSTEEL": "Materials", "HINDALCO": "Materials",
    "ULTRACEMCO": "Materials", "GRASIM": "Materials",
    "LT": "Industrials", "ADANIPORTS": "Industrials", "ADANIENT": "Industrials",
    "BHARTIARTL": "Telecom",
    "LICI": "Financials", "CANBK": "Financials", "PNB": "Financials",
    "BANKBARODA": "Financials", "UNIONBANK": "Financials",
    "ASHOKLEY": "Auto", "TVSMOTOR": "Auto",
}

# ETFs/index funds track a basket rather than one sector — flag them distinctly
# instead of forcing a single-company classification.
_ETF_SUFFIXES = ("BEES", "ETF", "IETF")


def sector_for(symbol: str | None) -> str:
    if not symbol:
        return "Other"
    upper = symbol.upper()
    if upper in _SECTOR_BY_SYMBOL:
        return _SECTOR_BY_SYMBOL[upper]
    if upper.endswith(_ETF_SUFFIXES):
        return "ETF"
    return "Other"
