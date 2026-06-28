## PROPOSAL — Multi-Index Directional Strangle (BANKNIFTY + SENSEX)

**Goal:** Run the same bias-driven strangle strategy on BANKNIFTY and SENSEX; fill 5-year
data gaps; compare performance profiles across indices.

Same bias engine (`backend/pdp/signals/bias.py`) reused unchanged — only instrument params differ.

> **Program alignment** (since `repo-restructure-and-claude-arch`): this is the **multi-index
> data + backtest track** feeding chunk 4 `strangle-execution-console` and chunk 8
> `flutter-backtest-console`. BANKNIFTY + SENSEX spot/options backfill is **in progress**.
> All paths are now under `backend/` (`backend/scripts/...`, `backend/backtest/configs/...`);
> run via `task backfill:* ` / `task backtest:strangle` from the repo root.

---

## 1. BANKNIFTY data backfill

- [ ] 1.1 Spot backfill: `uv run python scripts/backfill_spot.py --symbol BANKNIFTY --from 2021-01-01 --only-missing`
  - Security ID: look up from scrip master (Dhan IDX_I)
  - Store into `market_bars` with `security_id=<banknifty_sid>`
- [x] 1.2 VIX already shared — India VIX applies to all indices
- [ ] 1.3 Options backfill (expired): adapt `scripts/backfill_expired_options.py` for BANKNIFTY expiry calendar (Thursday weekly)
  - Strike step: 100 (BANKNIFTY)
  - Lot size history: 15 → 25 → 15 (check NSE lot size table)
- [x] 1.4 Audit: `uv run python scripts/audit_strangle_data.py --symbol BANKNIFTY`

---

## 2. SENSEX data backfill

- [ ] 2.1 Spot backfill: `uv run python scripts/backfill_spot.py --symbol SENSEX --from 2021-01-01 --only-missing`
  - BSE index — confirm Dhan security ID from scrip master
- [ ] 2.2 Options backfill: SENSEX options trade on BSE (weekly, Friday expiry)
  - Strike step: 100 (SENSEX)
  - Lot size: 10 (SENSEX)
  - Adapt `backfill_options.py` for BSE exchange segment
- [x] 2.3 Audit: `uv run python scripts/audit_strangle_data.py --symbol SENSEX`

---

## 3. BANKNIFTY backtest configs

- [x] 3.1 Create `backtest/configs/strangle_banknifty_hedged.yaml`:
  ```yaml
  underlying: BANKNIFTY
  underlying_security_id: "<banknifty_sid>"
  lot_size: 15          # verify current lot size
  strike_step: 100
  otm_steps: 2
  scale_lots: 2
  hedge_enabled: true
  hedge_prem_min: 2.0
  hedge_prem_max: 8.0   # BANKNIFTY premiums higher — wider band
  take_profit_pct: 0.5
  day_loss_limit: 20000 # higher cap for higher-premium index
  # ... same bias weights as NIFTY canonical config
  ```
- [x] 3.2 Run 5-year backtest: `task backtest:strangle -- --config-file backtest/configs/strangle_banknifty_hedged.yaml --from 2021-09-01 --to 2026-06-25 --out-dir backtest/runs`
  - Ran 2021-08-04 to 2024-12-31 (4yr data-complete window; 2025+ options gap being filled)
  - Result: Net +₹45.4L | PF 4.90 | Win 75% | MaxDD ₹41K | 827 days | run: strangle_20260628-211917
- [x] 3.3 Report year-by-year metrics; compare with NIFTY baseline

---

## 4. SENSEX backtest configs

- [x] 4.1 Create `backtest/configs/strangle_sensex_hedged.yaml` analogous to BANKNIFTY config
  - Strike step: 100 (SENSEX)
  - Lot size: 10
  - Hedge band: Rs 3–8 (test empirically)
- [x] 4.2 Run 5-year backtest; report metrics
  - Ran 2024-01-01 to 2026-06-25 (full options window available)
  - Result: Net +₹24.3L | PF 6.44 | Win 70% | MaxDD ₹55K | 607 days | run: strangle_20260628-212217

---

## 5. Runner + loader changes for multi-index

The current `strangle_loader.py` assumes NIFTY security IDs for VIX and PCR. Make it generic:

- [x] 5.1 Accept `underlying` and `security_id` as loader params; resolve from `StrangleConfig`
- [x] 5.2 PCR: for BANKNIFTY/SENSEX, compute from respective option chain OI (not NIFTY)
- [x] 5.3 VIX gate: India VIX (sid 21) applies to all — no change needed

---

## 6. Comparison report

- [x] 6.1 Generate a side-by-side table: NIFTY vs BANKNIFTY vs SENSEX (5-year Net, PF, MaxDD, Calmar, Win%, per-year)
- [x] 6.2 If all three are profitable with acceptable DD, consider running all three simultaneously (non-correlated premium income)
- [ ] 6.3 Confirm legs don't exceed Dhan NIFTY/BANKNIFTY/SENSEX margin limits when running concurrent strategies

---

## Acceptance criteria
- Per-year coverage ≥ 90% for both BANKNIFTY and SENSEX spot + options (audit report)
- 5-year backtest for each index completes without data errors
- Comparison report shows PF > 1.5 and MaxDD < 5% of annual net for at least one additional index
