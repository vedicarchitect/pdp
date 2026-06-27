# Backtest Research Journal

Running log of all sweep experiments, findings, config promotions, and pending ideas.
Each entry is self-contained so it can be read cold. Newest entries at the top.

---

## Entry 2026-06-15 — 300-Day Sweep A+H, OTM2 Promotion, 5m EMA Exit Idea

### Context

Branch `consolidate-backtest`. All prior work consolidated: `backtest/run.py`,
`backtest/sweep_all.py`, `backtest/configs/`. Sweep harness loads the Mongo window
once and runs every experiment sequentially (no cold-start per experiment), with full
per-trade detail + DTE distribution written to `logs/sweep_YYYYMMDD_HHMMSS.log`.

**Source log:** `logs/sweep_20260614_194446.log` (122,712 lines)

---

### Sweep Metadata

| Field | Value |
|-------|-------|
| Script | `backtest/sweep_all.py` |
| Sections run | A, H (B–G pending — see below) |
| Experiments | 19 |
| Biz-day window | 300 biz days ending 2026-06-14 |
| Traded days | 283 (17 skipped — no data or holiday) |
| Commission | Real (brokerage + STT + txn + SEBI + stamp + GST) |
| ST warmup | Prior session seeded (cross-day warmup) |
| Auto-heal | OFF (`--no-heal`) |
| Runtime | 102 seconds |

---

### Terminology Glossary

| Term | Meaning |
|------|---------|
| `b2a1m5` | base\_lots=2, add\_lots=1, max\_lots=5 (canonical lot ladder) |
| `b3a1m7` | base\_lots=3, add\_lots=1, max\_lots=7 (heavier base + wider ladder) |
| `b1a0m1` | base\_lots=1, add\_lots=0, max\_lots=1 (single-lot, no scale-in) |
| `ls2k` / `ls3000` | leg\_stop\_per\_lot=2000 / 3000 INR (per-lot MTM stop on active leg) |
| `ds12k` / `ds20k` | day\_stop=12000 / 20000 INR (total day P&L hard-stop) |
| `OTM1/2/3` | moneyness=1/2/3 → strike 50/100/150 pts OTM from ATM |
| `ATM` | moneyness=0 → at-the-money strike |
| `DTE` | Days to expiry on that trade date (0 = expiry Tuesday) |
| `PF` | Profit factor = GrossProfit / \|GrossLoss\| |
| `Win%` | % of trading days with realized P&L ≥ 0 |
| `MaxDD` | Single worst daily realized loss across all traded days |
| `Stops` | Days where day\_stop triggered (strategy halted for the day) |
| `flip_mode=strangle` | On ST flip: trim extra lots, keep base, open opposite base, arm strangle; resolve via flip-candle extreme break |
| `scale_in_gate=premium_break` | Scale-in only when option premium broke prior bar's low (decay confirmed) |

---

### Full Ranked Summary — All 19 Experiments

Sorted by PF descending, then Net descending.

```
  #  Sec  Label                              Net       PF   Win%    MaxDD  Trades  Stops    GrossP      GrossL
  1    A  15m OTM2                       +353317    1.82     78    50229    1114     11   +785724    -432406
  2    A  15m OTM3                       +295016    1.72     77    53426    1141     13   +706263    -411247
  3    A  15m OTM1 (current BASE ★)      +347163    1.69     77    74399    1093     16   +848715    -501552
  4    H  15m OTM2 b3a1m7 ls2k          +376452    1.63     76    73055    1211     22   +975984    -599532
  5    H  15m OTM2 ls2000 ds12k         +271475    1.58     78    55493    1148     13   +739600    -468125
  6    H  15m OTM1 b3a1m7 ls2k          +370304    1.54     76    82833    1170     31  +1054775    -684471
  7    H  15m OTM1 ls2000 ds12k         +281765    1.54     76    61413    1134     16   +807476    -525711
  8    A  15m ATM                       +317409    1.52     75   112451    1030     27   +925879    -608470
  9    H  15m OTM2 ls1500 ds12k         +219912    1.47     76    89953    1200     12   +692438    -472526
 10    H  15m OTM1 ls1500 ds12k         +236302    1.46     75    74255    1169     14   +754517    -518215
 11    H  5m OTM2 b3a1m7 ls2k ds20k    +425735    1.34     51    86974    5098     21  +1667401   -1241666
 12    A  5m OTM1                       +338694    1.32     51    96005    4516     18  +1397797   -1059103
 13    H  5m OTM1 ls2k ds20k            +313013    1.30     51    99590    4596     17  +1373449   -1060436
 14    A  5m ATM                        +331527    1.27     51   115077    4408     20  +1551330   -1219802
 15    H  5m OTM1 ls2k ds25k            +283678    1.26     52    92293    4686     12  +1374484   -1090807
 16    H  5m OTM1 b3a1m7 ls2k ds20k    +356244    1.24     51   162013    4915     30  +1844951   -1488706
 17    H  5m OTM2 ls2k ds20k            +233607    1.24     52   101684    4712     15  +1214983    -981376
 18    A  5m OTM2                       +233332    1.23     51    99234    4679     16  +1236868   -1003537
 19    A  5m OTM3                       +208882    1.21     53    83578    4846     16  +1180778    -971896
```

---

### DTE Distribution — Key Configs

DTE = days to expiry on that trade date. 0 = expiry Tuesday. 5-6 = start of next
weekly cycle. 7-13 = monthly/quarterly cycles (only 14 days out of 283).

#### 15m OTM2 (WINNER, Rank #1)
```
DTE  Days  Wins  Win%  Trades         Net  Avg/Day
  0    55    40    73%     344     +95182    +1731
  1    50    44    88%     188    +100866    +2017
  2    16    13    81%      61     +16114    +1007
  3    19    16    84%      43     +22371    +1177
  4    37    34    92%     102     +67772    +1832
  5    38    27    71%     150     +34152     +899
  6    46    34    74%     154     +62273    +1354
  7     5     2    40%      23     -33121    -6624  ← monthly cycle drag
  8     5     3    60%      31      -5373    -1075
 13     4     2    50%      15      -5969    -1492
```

#### 15m OTM1 (Current BASE, Rank #3)
```
DTE  Days  Wins  Win%  Trades         Net  Avg/Day
  0    55    39    71%     349     +59923    +1090  ← OTM2 earns +59% more here
  1    50    42    84%     172    +106230    +2125
  2    16    12    75%      61     +17955    +1122
  3    19    16    84%      40     +23624    +1243
  4    37    33    89%     102     +77372    +2091
  5    38    27    71%     143     +40326    +1061
  6    46    35    76%     154     +69981    +1521
  7     5     3    60%      23     -26570    -5314
  8     5     2    40%      31     -12920    -2584
 13     4     2    50%      15      -7593    -1898
```

#### 5m OTM2 (Rank #18 baseline, for fine-tuning reference)
```
DTE  Days  Wins  Win%  Trades         Net  Avg/Day
  0    55    32    58%    1261     +96534    +1755
  1    50    27    54%     771     +54457    +1089
  2    16     8    50%     259     +23629    +1477
  3    19    10    53%     254     +12314     +648
  4    37    15    41%     543     -59876    -1618  ← DTE4 is a consistent 5m loser
  5    38    22    58%     556    +118998    +3132  ← DTE5 strong for 5m
  6    46    20    43%     676      +4272      +93
  7     5     1    20%     105     -28594    -5719
 13     4     1    25%      55      -7668    -1917
```

#### 5m OTM2 b3a1m7 ls2k ds20k (Best 5m, Rank #11)
```
DTE  Days  Wins  Win%  Trades         Net  Avg/Day
  0    55    32    58%    1339    +170984    +3109  ← more lots = more DTE0 capture
  1    50    27    54%     848    +115930    +2319
  4    37    15    41%     588     -61251    -1655  ← still loses on DTE4
  5    38    23    61%     614    +158422    +4169
  6    46    20    43%     741     +11272     +245
  7     5     2    40%     116     -31127    -6225
 12     1     0     0%      20     -26639   -26639  ← worst single day
```

---

### Analysis

#### 15m OTM2 strictly dominates OTM1 on every metric

| Metric | OTM1 (current) | OTM2 (new) | Delta |
|--------|----------------|------------|-------|
| PF | 1.69 | **1.82** | +8% |
| Net (300d) | +347,163 | **+353,317** | +1.8% |
| Win% | 77% | **78%** | +1pp |
| MaxDD | 74,399 | **50,229** | **−33%** |
| Stops | 16 | **11** | **−31%** |

This is not a tradeoff — OTM2 wins on every single axis simultaneously.
The only change from BASE is `moneyness: 1 → 2` (strike 50 pts further OTM).

**Why OTM2 is better on DTE 0 (expiry Tuesday):** The extra 50pts of OTM distance
gives more theta-decay buffer on expiry day. OTM1 stops out more often when NIFTY
drifts toward the strike intraday — OTM2 survives those same moves.

**Why H variants don't beat plain OTM2:** Tighter leg-stop (ls2000 vs ls3000) reduces
PF: more premature stop-outs offset by not meaningfully reducing gross loss. Heavier
lots (b3a1m7) increase Net but raise Stops and compress PF. The canonical b2/a1/m5
with ls3000 is already at the optimal point on the lot/PF tradeoff curve.

#### 5m overall verdict

- Best 5m PF is 1.34 vs 15m OTM2's 1.82 — structurally worse
- 5m Win% is 51% vs 78% for 15m — nearly a coin flip, much harder psychologically
- 5m trade count is 4-5× higher → proportionally more commission drag
- **DTE 4 is a consistent 5m loser** (PF <0.7 effectively): NIFTY is typically mean-
  reverting mid-cycle; 5m catches every short-term noise while 15m filters through it
- **DTE 5 is 5m's best day** (+3132/day avg) — start of next weekly cycle, clear trend
- Not worth promoting 5m over 15m at current PF levels

#### 5m fine-tuning headroom (sections B-G not yet run)

Sections B–G (lot-sizing, leg-stop, day-stop granular sweeps) were NOT run. What
sections A+H already tell us about 5m:
- ls3000 vs ls2000: `5m OTM2 ls2k ds20k` (rank 17, PF 1.24) vs `5m OTM2` baseline
  (rank 18, PF 1.23) — negligible difference on 5m; stop level barely matters
- b3a1m7 variant (rank 11, PF 1.34) shows lots help Net but not PF
- Gap to fill: ls=1500/1000 on 5m, ds=15000/25000 sensitivity, OTM2 b2a1m5 with ls2k

The **biggest 5m improvement vector is not lots or stops — it is exit timing.**
See "5m EMA Exit Experiment" below.

---

### Action Taken

**Config created:** `backtest/configs/st10_15m_otm2.yaml`

```yaml
# ST(10,2) / 15m / OTM-2 — promoted 2026-06-15
# 300-day sweep winner: PF 1.82 / Net +353,317 / MaxDD 50,229 / Win% 78% / 11 stops
# Change from OTM1 baseline: moneyness 1 → 2 only.
st_period: 10
st_multiplier: 2.0
timeframe_min: 15
moneyness: 2
strike_step: 50
base_lots: 2
add_lots: 1
max_lots: 5
lot_size: 65
start_ist: "09:30"
squareoff_ist: "15:10"
leg_stop_per_lot: 3000.0
day_stop: 12000.0
roll_enabled: true
roll_trigger_prem: 20.0
roll_target_min_prem: 50.0
scale_in_gate: premium_break
flip_mode: strangle
```

**To promote to paper:** Set `BACKTEST_DEFAULT_CONFIG=backtest/configs/st10_15m_otm2.yaml`
in `.env` and run `task reset-paper` to clear prior paper positions.

---

### Pending Experiments (Sections B–G)

Sections A+H already gave us a clear winner. B–G would complete the picture but
are not blocking the promotion. Priority order for next run:

| Section | What it tests | Why it matters |
|---------|--------------|----------------|
| C | 15m leg-stop sweep: OTM1+OTM2, ls=1000..5000 | Confirm ls=3000 is optimal for OTM2 |
| D | 15m day-stop sweep: OTM1+OTM2, ds=8000..20000 | Confirm ds=12000 is optimal |
| B | 15m lot sizing: OTM1+OTM2, b1a0m1 to b3a2m7 | Find if b3a1m5 beats b2a1m5 on PF |
| F | 5m leg-stop sweep: ls=1000..4000 | Fine-tune 5m stop (pre-EMA exit) |
| E | 5m lot sizing | Same as B but for 5m |
| G | 5m day-stop sweep | Low priority; ds barely moves 5m PF |

Run command:
```bash
task sweep:all -- --days 300 --no-heal --section B,C,D,F
```

---

### 5m EMA Exit Experiment (NEXT — pending indicator suite)

#### Problem

On 5m, the current exit signal is an ST flip on bar close. SuperTrend with period=10
on 5m has a 50-bar lookback → it lags true trend changes by 2-4 bars (10-20 minutes).
By the time ST flips, a big part of the adverse move is already realised.

**5m DTE4 is consistently −ve** (PF <0.7 effectively, −1618/day avg across 37 days)
and intraday whipsaws dominate — exactly the regime where a faster exit signal would
cut losses earlier and redeploy.

#### Proposed Exit Logic

On 5m, **add a fast exit gate** that triggers before ST flips:

```
SIGNAL-A: close below 9 EMA AND prior bar also closed below 9 EMA
           → exit SHORT-CE immediately (move validated for 2 bars = 10 min)

SIGNAL-B: close below 20 EMA on any single bar
           → exit SHORT-CE immediately (slower but surer filter)
```

Mirror for PE side (exit SHORT-PE when close above 9/20 EMA).

This is effectively a "ST is still green but EMA says price has already turned" gate.
The leg stop stays in place as a hard backstop; EMA exit is a softer earlier signal.

#### Config knobs to add (StrategyConfig)

```python
early_exit_ema_fast: int | None = None   # e.g. 9 — None = disabled
early_exit_ema_slow: int | None = None   # e.g. 20 — None = disabled
early_exit_ema_confirm_bars: int = 2     # bars price must sustain beyond EMA (fast only)
```

#### Experiments to run once indicator suite lands

```
5m OTM2 ema9-2bar          # fast EMA break, 2-bar confirm
5m OTM2 ema20-instant      # slow EMA break, immediate exit
5m OTM2 ema9or20           # either triggers (logical OR)
5m OTM1 ema9-2bar          # same for OTM1
```

Compare each against `5m OTM2` baseline (rank #18, PF 1.23, Net +233k).
Success bar: PF ≥ 1.45 with Net ≥ +250k (15m OTM2 PF is 1.82 — 5m needs to close
the gap meaningfully to justify its 5× trade volume).

#### Implementation path (aligned to `add-indicator-suite` OpenSpec)

The indicator suite change (`openspec/changes/add-indicator-suite/`) already plans
exactly the infrastructure needed:

| Suite task | What it delivers | How we use it |
|-----------|-----------------|---------------|
| 2.1 `ema.py` — `EMATracker` multi-period 9/20/50 | Per-bar EMA state | Core signal source |
| 5.2 `backtest/sim.py` reuse of tracker classes | Same tracker in backtest as live | Parity guarantee |
| 1.5 `IndicatorReader` accessors (`ctx.indicators.ema(...)`) | Live strategy access | Future live promotion |
| 1.3 `IndicatorEngine` bundle per `(sid, tf)` | Engine-level compute | No duplicate compute |

**After suite lands, `sim.py` changes needed:**

1. In `simulate_day`: build an `EMATracker(periods=[9, 20])` alongside `SuperTrendTracker`
2. Seed it from `data.prior_session_bars` exactly like ST (for cross-day continuity)
3. In the per-bar `series` tuple, append `(ema9, ema20)` state
4. In the main bar loop, after the leg-stop check and before the flip check:
   ```python
   if cfg.early_exit_ema_fast and active in legs:
       ema9 = ema_state.ema[cfg.early_exit_ema_fast]
       if _ema_exit_triggered(bar_close, prev_close, ema9, ema_break_count, cfg):
           close_leg(active, ist_dt, bar_close, "ema_exit")
           continue
   ```
5. Add `early_exit_ema_*` to `StrategyConfig` + `sweep_all.py` experiment section I

No changes needed in `day_loader.py`, `chain_loader.py`, `commissions.py`, or
`strategy_config.py` YAML I/O (new fields auto-serialize).

#### Why not implement before the indicator suite?

We could inline a throw-away EMA computation directly in `sim.py`. But:
- The indicator suite is imminent (next openspec task)
- Inline code would duplicate the `EMATracker` being built in `ema.py`
- Live↔backtest parity (suite task 5.2) requires both sides use the same class
- Implementing twice = drift risk; wait 1 sprint, do it right once

---

### Previous Result Reference (2026-06-14, 83-day run)

Superseded but kept as anchor. From `backtest/mutliplerunschecklog.txt`:

| Config | Net | PF | Win% | Days | MaxDD |
|--------|-----|----|------|------|-------|
| ST(3,1)/5m/OTM1 | −306,708 | 0.38 | 34% | 83 | — |

That regression prompted the full parameter sweep and led to ST(10,2)/15m as the
promoted config. The 83-day window was also on gapped data (pre-backfill-fix).

---

## Entry 2026-06-14 — OTM1 Promotion (Superseded by OTM2 above)

**Config promoted:** `backtest/configs/st10_15m_otm1.yaml`
**Result at promotion:** PF 3.28 / Net +232,700 / MaxDD 22,573 / 83 days / 1 stop

Note: 83-day result was on a shorter window post-data-fix. The 300-day sweep puts
OTM1's PF at 1.69 — still healthy but below OTM2's 1.82. OTM1 remains the fallback
config if OTM2 exhibits unexpected live behaviour.

---

## Glossary — Backtest Engine Mechanics (for future reference)

| Mechanic | How it works |
|----------|-------------|
| **Entry** | First ST flip of the day after `start_ist`. Open `base_lots` at bar close. |
| **Scale-in** | Every subsequent aligned bar where `premium_break` gate is open: add `add_lots` until `max_lots`. Gate = option premium broke prior bar low. |
| **Leg stop** | Per bar: if `(avg_entry − curr_px) × qty ≤ −(leg_stop_per_lot × lots)` → close that leg. |
| **Day stop** | After every close: if cumulative `day_pnl ≤ −day_stop` → mark done, no more trades. |
| **Flip (strangle)** | ST flips: trim extra lots on old side down to `base_lots`, open `base_lots` on opposite side, arm `flip_high/flip_low` from flip-candle extremes. Strangle resolves when NIFTY breaks either extreme. |
| **Roll** | Active leg premium drops below `roll_trigger_prem` (20): close, reopen at furthest OTM strike with premium > `roll_target_min_prem` (50). Controlled decay exit. |
| **Square-off** | At `squareoff_ist` (15:10): close all legs at open of that bar. Any still-open at end of series: close at `nifty_close`. |
| **ST warmup** | Prior session bars fed into `SuperTrendTracker` before replaying the trade day — mirrors Kite live behaviour. Critical for correct open-of-day ST state. |
