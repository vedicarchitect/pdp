# Design — Live Event Publisher

## Goals / Non-goals

- **Goal**: turn the existing indicator + option-analytics intelligence into de-duplicated, real-time, position-aware events delivered to an in-app feed and to the browser/desktop via push.
- **Goal**: be position-aware for *manual* Dhan positions the app did not place.
- **Non-goal**: order placement / modification. This is alerts-only (IP-whitelist blocks orders anyway).
- **Non-goal**: replacing the existing `alerts/` engine. The two coexist; `alerts/` stays for user-defined single-security threshold rules.

## Architecture

```
Dhan tick feed ─► TickRouter._handle ─► IndicatorEngine.on_bar(bar)  (existing)
                                     └─► EventService.on_bar(bar, snapshot)   [NEW, sync, cheap]
                                              │
PositionSync (poll get_positions 30s) ───────┤  monitored positions + MTM peak
OptionsChainPoller / OptionsHub ─────────────┤  on_chain(underlying, snapshot)
                                              ▼
                                        Detector library
                                   (spot · position · oi)
                                              │ Event | None  (per-key dedup + cooldown)
                                              ▼
                          ┌──────────────── EventService.emit(event) ───────────────┐
                          ▼                          ▼                                ▼
                  EventsHub (/ws/events)     EventStore (Mongo, async queue)   WebPush (pywebpush)
```

### Why a new module, not an extension of `alerts/`

`AlertEvaluator` is per-tick, single-security, and keyed off DB rows holding one `(condition, threshold)`. The new requirements are bar-driven, need previous-bar state (crosses/flips), are position-aware (OTM distance, trailing MTM), and span composite conditions (safe-to-exit). A dedicated `events/` module keeps `alerts/` simple and avoids overloading its tick hot path.

### Hot-path discipline (Non-negotiable #5: tick→WS p99 ≤ 50ms)

`EventService.on_bar` runs **only on bar close** (not every tick), does float comparisons against the already-computed `Snapshot`, and never awaits. All I/O (Mongo write, web-push HTTP) is pushed onto an `asyncio.Queue` drained by background workers. Per-tick work is limited to price-level / OTM-distance / MTM checks, which are O(#monitored positions) float comparisons reading the Redis LTP already in hand.

## Detectors

Each detector is a small stateful callable keyed by `(sid, tf, detector)` holding the previous observation. `evaluate(...) -> Event | None`. Detectors never do I/O.

All spot/indicator detectors run **per configured timeframe** (`EVENTS_SPOT_TIMEFRAMES`, default `["5m","15m","30m","1H","1D"]`) so the same condition is reported independently on each TF. Position/OI/portfolio detectors run against monitored legs + their underlying.

**A. Price levels & confluence**
| Detector | Event type | Trigger | Reads |
|----------|-----------|---------|-------|
| `price_level_cross` | `PRICE_LEVEL_CROSS` | close crosses a configured level (23600/24000…) | bar close, `EVENTS_WATCH_LEVELS` |
| `level_proximity` | `LEVEL_PROXIMITY` | price within band of any tracked level (PDH/PDL/PWH/PWL/PMH/PML/day-H/L, pivots, Camarilla, fib, FVG edge, EMA, VWAP, swing) | snapshot (multi-family) |
| `confluence_zone` | `CONFLUENCE_ZONE` | ≥ `EVENTS_CONFLUENCE_MIN` level-sources cluster within `EVENTS_CONFLUENCE_BAND_PTS` of price | snapshot (multi-family) + OI walls |

**B. Trend / momentum (per TF)**
| Detector | Event type | Trigger | Reads |
|----------|-----------|---------|-------|
| `ema_crossover` | `EMA_CROSS` | a configured EMA pair crosses (9/20, 9/50, 20/50) | `snapshot.ema.values` |
| `price_ema_cross` | `PRICE_EMA_CROSS` | close crosses a configured EMA (e.g. 50) | `snapshot.ema`, bar close |
| `supertrend_flip` | `SUPERTREND_FLIP` | ST(10,2) direction flips on any TF | `engine.get(sid, tf)` |
| `psar_flip` | `PSAR_FLIP` | `psar.direction` changes sign | `snapshot.psar` |
| `macd_cross` | `MACD_CROSS` | MACD line crosses signal / zero | `snapshot.macd` |
| `elder_impulse` | `ELDER_IMPULSE_CHANGE` | regime green↔red↔blue change | `snapshot.elder_impulse` |
| `elliott_wave` | `ELLIOTT_WAVE` | `wave_label` changes | `snapshot.elliott` |
| `ml_signal_flip` | `ML_SIGNAL_FLIP` | ML directional signal flips | `engine.get_ml_signal` |
| `rsi_extreme` | `RSI_EXTREME` | RSI crosses OB/OS band (+ divergence) | `snapshot.rsi` |

**C. Range / breakout / volume**
| Detector | Event type | Trigger | Reads |
|----------|-----------|---------|-------|
| `level_break` | `LEVEL_BREAK` | close breaks day-H/L, PDH/PDL, PWH/PWL, PMH/PML | `snapshot.pivots`, `snapshot.period_levels` |
| `custom_range_break` | `CUSTOM_RANGE_BREAK` | spot breaks a position's configured strangle range | `EVENTS_POSITION_RANGES` / position cfg |
| `volume_spike` | `VOLUME_SPIKE` | bar volume z-score ≥ threshold (futures) | rolling volume window |
| `volume_sr` | `VOLUME_SR` | rejection at volume-profile POC/VAH/VAL | `snapshot.volume_profile` |
| `gap_open` | `GAP_OPEN` | session-open gap vs prior close ≥ threshold | first bar of session + prior close |

**D. Options / OI / Greeks**
| Detector | Event type | Trigger | Reads |
|----------|-----------|---------|-------|
| `oi_wall` | `OI_WALL` | strong OI S/R strike + price rejection | `option_chains` snapshots |
| `oi_buildup` | `OI_BUILDUP` | OI at a held/ATM strike rises ≥ % over window | `option_chains` snapshots |
| `oi_volume_spike` | `OI_VOLUME_SPIKE` | sudden OI/volume jump at a strike | `option_chains` snapshots |
| `pcr_shift` | `PCR_SHIFT` | PCR crosses configured band | `compute_pcr` |
| `gex_wall` | `GEX_WALL` | spot within N pts of largest \|GEX\| strike | `compute_gex` |
| `max_pain_pin` | `MAX_PAIN_PIN` | max-pain shift / spot pinning near expiry | `compute_max_pain` |
| `iv_shift` | `IV_SHIFT` | IV spike/crush at held strikes | chain IV |
| `delta_neutral_drift` | `DELTA_NEUTRAL_DRIFT` | aggregate portfolio delta leaves neutral band | per-position delta |
| `breakeven_breach` | `BREAKEVEN_BREACH` | spot breaches strangle/straddle breakeven | monitored legs |
| `expiry_countdown` | `EXPIRY_COUNTDOWN` | time-to-expiry milestones / decay acceleration | expiry + clock |

**E. Position / P&L / portfolio**
| Detector | Event type | Trigger | Reads |
|----------|-----------|---------|-------|
| `mtm_swing` | `MTM_SWING` | position MTM moves ≥ threshold since last emit | MonitoredPosition + LTP |
| `otm_distance` | `OTM_DISTANCE` | spot within N pts of a held OTM strike | spot LTP + strike |
| `safe_to_exit_trail` | `SAFE_TO_EXIT_TRAIL` | open MTM retraces ≥ % from session peak | `mtm_peak` |
| `safe_to_exit_momentum` | `SAFE_TO_EXIT_MOMENTUM` | PSAR flip + price⇄EMA50 against the position | snapshot + side |
| `leg_stop_proximity` | `LEG_STOP_PROXIMITY` | leg LTP nears a configured stop | leg LTP |
| `directional_junction` | `DIRECTIONAL_JUNCTION` | directional trade hits a critical confluence/flip | snapshot + position |
| `portfolio_stats` | `PORTFOLIO_STATS` | periodic/threshold digest: # trades, premium received, P&L, max profit/loss | journal + portfolio |
| `position_change` | `POSITION_CHANGE` | a leg opened/closed/changed since last sync | PositionSync diff |

Detectors marked above as needing rolling state (volume z-score, OI window, divergence) keep a small bounded ring buffer keyed by `(sid, tf)` inside the detector — no engine changes.

## De-duplication

A condition that stays true must not spam. Each `(sid, detector, level-key)` carries a small state machine mirroring `AlertEvaluator`: `IDLE → FIRED → (cleared when condition releases)`, plus a `EVENTS_COOLDOWN_SECONDS` (default 300) floor between repeat emissions of the same key. Crosses/flips are inherently edge-triggered (compare prev vs current) so they fire once per edge.

## Position sync

`PositionSync` background loop (`EVENTS_POSITION_SYNC_SECONDS`, default 30):
1. Live + creds → `await asyncio.to_thread(client.get_positions)` (mirrors `cli/progress/commands/positions.py`); else read the PG `positions` table.
2. Map each open leg to `MonitoredPosition(security_id, underlying, segment, strike, option_type, expiry, net_qty, avg_price, side, mtm_peak)`.
3. Diff against the current set; auto-subscribe new legs (`NSE_FNO`) and their underlying spot (`IDX_I`, via `UNDERLYING_MAP`) through the `DhanTickerAdapter`; drop unsubscribed legs.
4. MTM per tick = `net_qty × (ltp − avg_price)`; update `mtm_peak = max(mtm_peak, mtm)` for trailing-exit.

Underlying resolution uses `pdp.options.dhan_client.UNDERLYING_MAP` (NIFTY→(13, IDX_I), etc.) and the instruments registry for the option-leg → underlying mapping.

## `period_levels` indicator family (PWH/PWL/PMH/PML)

New `src/pdp/indicators/period_levels.py` following the standard tracker protocol `update(high, low, close, volume, bar_time) -> PeriodLevelsState | None`:
- Accumulates current-week and current-month H/L; on a week boundary (ISO week change) freezes the completed week as `pwh/pwl`; on a month boundary freezes `pmh/pml`. Also exposes `pdh/pdl` for symmetry.
- `seed_prior_levels(...)` called by warmup, computed from MongoDB `market_bars` daily aggregation for the trailing week/month.
- Wired through `registry.py`, `snapshot.py` (`period_levels: PeriodLevelsState | None`), `engine.py` (`get_period_levels`, `_SUITE_FAMILIES`), `warmup.py`, and `IndicatorReader.period_levels()` — the 6-step "add a family" checklist in `indicators/CLAUDE.md`.

## Event model & storage

```python
class EventType(str, Enum):
    # A. price levels & confluence
    PRICE_LEVEL_CROSS, LEVEL_PROXIMITY, CONFLUENCE_ZONE
    # B. trend / momentum
    EMA_CROSS, PRICE_EMA_CROSS, SUPERTREND_FLIP, PSAR_FLIP, MACD_CROSS,
    ELDER_IMPULSE_CHANGE, ELLIOTT_WAVE, ML_SIGNAL_FLIP, RSI_EXTREME
    # C. range / breakout / volume
    LEVEL_BREAK, CUSTOM_RANGE_BREAK, VOLUME_SPIKE, VOLUME_SR, GAP_OPEN
    # D. options / OI / greeks
    OI_WALL, OI_BUILDUP, OI_VOLUME_SPIKE, PCR_SHIFT, GEX_WALL, MAX_PAIN_PIN,
    IV_SHIFT, DELTA_NEUTRAL_DRIFT, BREAKEVEN_BREACH, EXPIRY_COUNTDOWN
    # E. position / P&L / portfolio
    MTM_SWING, OTM_DISTANCE, SAFE_TO_EXIT_TRAIL, SAFE_TO_EXIT_MOMENTUM,
    LEG_STOP_PROXIMITY, DIRECTIONAL_JUNCTION, PORTFOLIO_STATS, POSITION_CHANGE
class Severity(str, Enum): INFO, WARNING, CRITICAL

@dataclass(slots=True)
class Event:
    event_type: EventType
    severity: Severity
    security_id: str
    underlying: str | None
    timeframe: str | None
    title: str           # short, e.g. "NIFTY 15m: 50-EMA crossed up"
    message: str         # human sentence, IST-stamped
    payload: dict        # raw numbers for the UI
    ts: datetime         # UTC; rendered IST in UI (user preference)
```

Persisted to MongoDB `events` (TTL `EVENTS_TTL_DAYS`, default 14), indexed `(ts desc)` and `(security_id, event_type, ts)`. History via `GET /api/v1/events`.

## Delivery

- **WebSocket** `/ws/events` via `EventsHub` (copy of `AlertsHub`: bounded per-client queue, drop-oldest, backfill last N on connect).
- **Web Push** (`push.py`): `pywebpush` + VAPID keys (`EVENTS_VAPID_PUBLIC_KEY` / `_PRIVATE_KEY` / `_SUBJECT`). Subscriptions stored in PG `push_subscriptions(endpoint PK, p256dh, auth, created_at)`. Frontend `public/sw.js` handles `push` → `showNotification`. Only events at/above `EVENTS_PUSH_MIN_SEVERITY` (default WARNING) are pushed; the in-app feed shows everything. Expired (410/404) subscriptions are pruned.

## Settings (all via `get_settings()`)

`EVENTS_ENABLED` (true), `EVENTS_SPOT_TIMEFRAMES` (["5m","15m","30m","1H","1D"]), `EVENTS_EMA_PAIRS` ([[9,20],[9,50],[20,50]]), `EVENTS_PRICE_EMA_PERIODS` ([50]), `EVENTS_WATCH_LEVELS` (dict underlying→list[float]), `EVENTS_PROXIMITY_BAND_PTS` (30), `EVENTS_CONFLUENCE_MIN` (2), `EVENTS_CONFLUENCE_BAND_PTS` (25), `EVENTS_OTM_DISTANCE_PTS` (100), `EVENTS_MTM_SWING_INR` (5000), `EVENTS_TRAIL_GIVEBACK_PCT` (30), `EVENTS_OI_BUILDUP_PCT` (20), `EVENTS_OI_VOLUME_SPIKE_Z` (3.0), `EVENTS_VOLUME_SPIKE_Z` (3.0), `EVENTS_PCR_BANDS` ([0.7, 1.3]), `EVENTS_GEX_WALL_PTS` (50), `EVENTS_DELTA_NEUTRAL_BAND` (0.15 of net qty), `EVENTS_GAP_PCT` (0.5), `EVENTS_POSITION_RANGES` (dict position-key→[low,high]), `EVENTS_STATS_INTERVAL_SECONDS` (300), `EVENTS_POSITION_SYNC_SECONDS` (30), `EVENTS_COOLDOWN_SECONDS` (300), `EVENTS_TTL_DAYS` (14), `EVENTS_PUSH_ENABLED` (false), `EVENTS_PUSH_MIN_SEVERITY` ("WARNING"), `EVENTS_VAPID_PUBLIC_KEY` / `_PRIVATE_KEY` / `_SUBJECT`.

Note: `1D` (daily) timeframe requires daily-bar support in `BarAggregator` + warmup; added as part of this change so daily EMA/level detectors work.

## Failure modes

- Dhan `get_positions()` error → keep last known set, log `position_sync_failed`, retry next cycle (graceful, like `_show_dhan_positions`).
- No ML model / missing snapshot family → detector returns None (no event), never raises.
- Web-push 410/404 → prune subscription. Other push errors logged, not retried inline.
- `EVENTS_ENABLED=false` → `EventService.on_bar` is a no-op; zero hot-path cost.
- Paper/no-creds → position sync reads PG table; spot/indicator + level detectors still run on whatever is subscribed.

## Alternatives considered

- *Extend `alerts/` with new condition types* — rejected: bloats the tick hot path and the DB-row rule model can't express edge-triggered / composite / position-aware conditions cleanly.
- *Redis Streams as the event bus* — deferred: in-process callbacks + Mongo history meet current needs; a Streams consumer can be added later for external subscribers without changing detectors.
- *Compute PWH/PWL/PMH/PML in the detector* — rejected: violates Non-negotiable #4 (indicators compute once in the engine; detectors consume).
