# Tasks — intraday-directional-selling

## 1. Shared pure decision core
- [x] 1.1 `pdp/signals/intraday_directional.py`: `IntradayInputs`, `IntradayParams`, `IntradayState`,
      `Side`, `ExitReason`, `EntrySignal`, `ExitSignal`. No I/O; no `orders`/`db`/`mongo`/`market`
      imports. Reuse `pdp.signals.bias.CamLevels`.
- [x] 1.2 `evaluate_entry()` — 4-condition AND gate per side; returns the per-condition pass map for
      the decision trace. Missing input ⇒ condition fails (fail-closed).
- [x] 1.3 `evaluate_scale_in()` — 15-min ladder, `initial_lots` → `max_lots` in `scale_lots_step`
      increments; skipped (not deferred) when conditions break; never exceeds `max_lots`.
- [x] 1.4 `evaluate_exit()` — 8 rules in fixed priority: `day_loss_cap` → `square_off` →
      `unreal_loss_stop` → `premium_rise_stop` → `underlying_st_flip` → `option_st_flip` →
      `ema20_break_sustained` → `cam_rejection_sustained`.
- [x] 1.5 Sustained-condition trackers on `IntradayState` (EMA20 break bar counter with reset;
      Camarilla rejection counter with reset) so both paths advance them identically.
- [x] 1.6 `evaluate_rollup()` — signal a roll to ATM when premium < `roll_trigger_prem`, subject to
      `roll_target_min_prem`, `max_rolls_per_day`, and `roll_cutoff_ist`; lot count preserved. The
      caller owns the all-or-nothing execution.
- [x] 1.7 Re-entry cooloff: `reentry_cooloff_minutes` (default 15) blocks entry after any exit
      except `day_loss_cap`/`square_off`, which end the session.

## 2. Backtest path
- [x] 2.1 `pdp/backtest/intraday_config.py` — `IntradayDirectionalConfig` dataclass; `from_dict`
      (rejects unknown keys) / `from_yaml` / `to_dict` / `to_yaml` / strict `validate()`. Reuse
      `strangle_config.lot_size_for_date` and `SECURITY_IDS` so notional sizing matches the strangle
      era-for-era (comparability requirement).
- [x] 2.2 `pdp/backtest/intraday_loader.py` — `build_intraday_day()`. Reuse `_resample_spot_ist`,
      `_prior_session_1m`, `_prior_days_1m`, `_ema_series`, `_st_psar_series`, `_option_series_reads`,
      `_asof`/`_at` from `strangle_loader.py`; `resolve_from_chain` from `sim.py`.
- [x] 2.3 Session-TWAP series (anchored cumulative mean of `(h+l+c)/3` on 1m, sampled at decision-bar
      closes) + ORB strictly from the 09:15-stamped 15m bar.
- [x] 2.4 Per-strike 5m SuperTrend(10,2) series for the *held* strike (not just ATM), memoised per
      resolved strike as `_option_series_reads` already does.
- [x] 2.5 `pdp/backtest/intraday_sim.py` — `simulate_intraday_day(cfg, data, commission_fn, trace,
      decisions)`. Reuse `DayResult`/`Trade`/`LegRecord`/`Leg`/`price_at`/`select_strike` from
      `sim.py` unchanged. Rollup-to-ATM implemented all-or-nothing.
- [x] 2.6 Decision events use the existing closed vocabulary (`entry`, `scale_in`, `exit`, `st_flip`,
      `rollup`, `reentry`) so `/backtest:explain` + `/backtest:vs-paper` work unmodified.
- [x] 2.7 `backend/backtest/intraday_run.py` — CLI mirroring `strangle_run.py`; quarter chunking,
      `warmup_prefix`, `load_window`, `RunWriter`, `aggregate`, `within_dte`, cadence-gap reporting.
- [x] 2.8 `Taskfile.yml`: `backtest:intraday` task.
- [x] 2.9 Backtest configs `backend/backtest/configs/intraday_nifty.yaml` + `intraday_banknifty.yaml`.

## 3. Live path
- [x] 3.1 `pdp/strategy/fills.py` — extract `_await_option_ltp`, `_await_fill_avg_px`,
      `_resolve_fill_price`, `_confirm_fill_or_recover` from `directional_strangle.py` as shared
      functions; **repoint `DirectionalStrangle` at them** so invariant 6 exists in exactly one place.
      No behaviour change; existing strangle tests must stay green.
- [x] 3.2 `atm_suite.option_trend_read(option_bars_col, security_id, since, tf)` — factored out of
      `atm_trend_read` so a held strike's own 5m ST(10,2) can be read. `atm_trend_read` delegates to it.
- [x] 3.3 `pdp/strategies/intraday_directional.py` — `IntradayDirectional(Strategy)`: `on_init`,
      `on_bar` (5m decisions, 15m ORB, 1m TWAP), `on_tick` (premium stops + rollup trigger),
      `on_shutdown`, `state()`, `check_readiness()`.
- [x] 3.4 Apply the 8 inherited invariants: `_legs` single map + `_add_leg`/`_remove_leg`,
      `_lock_for(sid)` on every broker read-modify-write, close side from broker sign,
      `min(leg_lots, broker_lots)`, durable `StrategyLeg` rows + `_rehydrate_legs`, shared
      fill-confirmation (3.1), per-sid lot cap inside the lock, `_reconcile_loop` on a timer.
- [x] 3.5 Day handling: `_maybe_reset_day` (ORB, TWAP accumulator, counters, baselines),
      `_record_day_baseline`/`_day_realized`, Redis halt marker surviving same-day restart,
      `_maybe_resolve_lot_size` (instruments table authoritative).
- [x] 3.6 Rollup-to-ATM on the live path with the `_roll_leg` all-or-nothing discipline + the
      `_rolling` single-claim guard + post-reopen verification.
- [x] 3.7 `backend/strategies/intraday_directional_nifty.yaml`. Watchlist sid `13` with `1m/5m/15m/1D`
      and an `ema`(9,20,50) + `pivots` + `period_levels` suite. **Do not** include
      `- family: supertrend` (not a registry family; silently ignored) — `st_10_2` comes from the
      matrix variants on any suited `(sid, tf)`.

## 4. Registry + tooling
- [x] 4.1 `pdp/strategy/unified_registry.py`: `intraday_directional` branch in `register_strategy`
      and dialect detection in `_load_backtest_entries`; add new knobs to `PARAM_BOUNDS`.
- [x] 4.2 `pdp/backtest/job_handlers.py`: launchable via the existing job/API path.
- [x] 4.3 `.claude/skills/strategy-add/SKILL.md`: add the new `kind` to its list.

## 5. Tests
- [x] 5.1 `tests/signals/test_intraday_directional.py` — each entry condition blocking independently;
      each of the 8 exits; exit priority order; scale-in ladder + clock; one-position-at-a-time;
      rollup signal; fail-closed on missing inputs.
- [x] 5.2 `tests/backtest/test_intraday_sim.py` — synthetic day: entry, scale, rollup, each exit,
      square-off, commissions applied, no look-ahead.
- [x] 5.3 `tests/strategies/test_intraday_directional_live.py` — the 8 invariants: duplicate-leg
      refusal, broker-sign close, `min(leg,broker)` lots, fill-confirmation adoption, lot cap under
      lock, rehydration, halt-survives-restart, roll all-or-nothing.
- [x] 5.4 **Parity test** `tests/test_intraday_parity.py` — same synthetic bars through the backtest
      loader and a stubbed live input builder ⇒ identical `IntradayInputs` and identical signal
      sequences. (This is the enforcement `bias.py` never got.)
- [x] 5.5 `task test` green (baseline **1219 passed**), `ruff` clean, `pyright` adds no new errors in
      `pdp/`.

## 6. Backtest runs + comparison
- [x] 6.1 Data pre-check done by direct `option_bars` query (2026-07-26): NIFTY 193 expiries with the
      763-day blackout 2020-12-03..2023-01-05 STILL PRESENT plus 16 gaps of 12-21 days; BANKNIFTY 263
      expiries, 0 gaps. Per-chunk `cadence-gap` counts recorded in each run log.
- [x] 6.2 NIFTY **2023-01-06 → 2026-07-25** (clean window) — primary result: 794 traded days,
      Net +Rs 6,72,580, PF 1.17, Win 46%, MaxDD Rs 1,84,500, 8276 trades, 240 day-cap halts.
- [x] 6.3 NIFTY **2021-07-01 → 2026-07-25** (literal 5yr): 799 traded days, Net +Rs 6,81,718,
      PF 1.17, Win 47%, MaxDD Rs 1,84,500, 8340 trades, 242 halts — but **497 of those days resolved
      their expiry across a coverage gap**. The extra 18 months added only **5 traded days** over the
      clean window, which is itself the proof the 763-day blackout is real: there is essentially no
      tradeable NIFTY option history before 2023-01-06. Treat 6.2 as the NIFTY answer.
- [x] 6.4 BANKNIFTY **2021-08-05 → 2026-07-25** (0 gaps) — the genuine 5-year read: 1190 traded days,
      Net +Rs 12,81,932, PF 1.18, Win 43%, MaxDD Rs 2,87,568, 11765 trades, 455 halts, 0 cadence-gap.
- [ ] 6.5 Sweep `moneyness [0,-1,-2]`, `unreal_loss_pct [0.15,0.20,0.30]`, `dte_max [3,6]`,
      `hedge_enabled [true,false]`.
- [x] 6.6 `directional_strangle` NIFTY over the **identical** window (2023-01-06 → 2026-07-25,
      `strangle_nifty_hedged.yaml`): Net +Rs 75,50,580, PF 8.04, Win 82%, MaxDD Rs 42,022,
      14487 trades, 34 halts.

      | | intraday directional | directional strangle |
      |---|---|---|
      | Net | +Rs 6,72,580 | **+Rs 75,50,580** (11.2x) |
      | PF | 1.17 | **8.04** |
      | Win | 46% | **82%** |
      | MaxDD | Rs 1,84,500 | **Rs 42,022** (4.4x smaller) |
      | Halted days | 240 / 794 | **34 / 926** |

      **Verdict: do not promote.** The intraday strategy is worse on every axis — a fraction of
      the return with 4.4x the drawdown — against the same data, same commissions, same
      no-slippage assumption. The Rs 10k day cap is ~1.3x the total credit collected on 3 ATM
      lots, so it halts ~30% of sessions. The engine was verified correct before this
      conclusion was drawn (2026-06-02 traced bar-by-bar: ORB/VWAP/ST/EMA gating, entries,
      scale-ins and each exit fired exactly as specified), so this is the spec's economics, not
      an implementation fault.

## 7. Live verification + archive
- [ ] 7.1 `task dev:trade` boot smoke during market hours: `indicator_seeding_summary` shows EMA9/20
      seeded and `st_10_2` present, ORB captured at 09:30, no `WARMUP_INCOMPLETE` disarm. Paper only.
- [ ] 7.2 `openspec validate --strict intraday-directional-selling`.
- [x] 7.3 Docs: `backend/pdp/strategies/CLAUDE.md`, `backend/pdp/backtest/CLAUDE.md`,
      `backend/strategies/CLAUDE.md`, `docs/RUNBOOK.md`.
- [ ] 7.4 `openspec archive intraday-directional-selling`.
