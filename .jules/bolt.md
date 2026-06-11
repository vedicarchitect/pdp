## 2026-06-11 - Optimize max pain compute
**Learning:** O(n^2) loop calculating max pain in `pdp/options/analytics.py` was slowing down polling per expiry.
**Action:** Used a running sum window to calculate in O(n).
