"""Bar-by-bar options strategy replay engine.

Uses the ``option_bars`` MongoDB collection (fixed strike contracts) to replay
multi-leg options strategies with SL/target/trailing/re-entry logic.
"""
from __future__ import annotations

import calendar
import math
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import structlog

from pdp.backtest.commissions import CommissionCalculator, NullCommissionCalculator
from pdp.backtest.options_strategy import LegConfig, OptionsStrategyConfig, SLTargetSpec
from pdp.settings import get_settings

log = structlog.get_logger()

_IST = timedelta(hours=5, minutes=30)
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    date: str
    entry_time: str
    exit_time: str
    legs: list[dict]
    pnl: float
    exit_reason: str
    re_entry_count: int = 0


@dataclass
class OptionsBacktestResult:
    config_name: str
    date_range: tuple[date, date]
    total_pnl: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    equity_curve: list[dict]
    daily_pnl: list[dict]
    weekday_stats: dict[str, dict]
    trade_log: list[dict]
    commissions_total: float


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

@dataclass
class _LegState:
    config: LegConfig
    strike: float
    expiry: date
    entry_price: float
    entry_time: str
    current_price: float = 0.0
    closed: bool = False
    exit_price: float = 0.0
    exit_time: str = ""

    def pnl_points(self) -> float:
        """Aggregate P&L in premium points (lots-adjusted, not INR)."""
        price = self.exit_price if self.closed else self.current_price
        diff = (self.entry_price - price) if self.config.side == "SELL" else (price - self.entry_price)
        return diff * self.config.lots


@dataclass
class _Position:
    legs: list[_LegState]
    net_entry_premium: float = 0.0  # sum(entry_price * lots) at open — used for percent-type SL
    re_entry_count: int = 0
    max_pnl: float = 0.0
    trailing_sl_level: float | None = None

    def combined_pnl(self) -> float:
        return sum(leg.pnl_points() for leg in self.legs)

    def update_trailing(self, trail_after: float, trail_step: float) -> None:
        pnl = self.combined_pnl()
        if pnl > self.max_pnl:
            self.max_pnl = pnl
        if self.max_pnl >= trail_after:
            new_level = self.max_pnl - trail_step
            if self.trailing_sl_level is None or new_level > self.trailing_sl_level:
                self.trailing_sl_level = new_level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strike_step(underlying: str) -> int:
    u = underlying.upper()
    if "BANK" in u or "SENSEX" in u:
        return 100
    return 50


def _atm(spot: float, step: int) -> float:
    return round(spot / step) * step


def _parse_time(t: str) -> time:
    h, m = map(int, t.split(":"))
    return time(h, m)


def _sl_threshold(spec: SLTargetSpec, net_entry: float) -> float:
    """Convert SLTargetSpec to a points threshold, handling percent-type."""
    if spec.type == "percent":
        return net_entry * spec.value / 100.0
    return spec.value


def _biz_days_in_range(from_date: date, to_date: date) -> list[date]:
    days, d = [], from_date
    while d <= to_date:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _resolve_expiry(d: date, selection: str) -> date:
    if selection in ("weekly", "nearest"):
        days_ahead = (1 - d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return d + timedelta(days=days_ahead)
    # monthly: last Thursday of current or next month
    year, month = d.year, d.month
    last_day = calendar.monthrange(year, month)[1]
    candidate = date(year, month, last_day)
    while candidate.weekday() != 3:
        candidate -= timedelta(days=1)
    if candidate >= d:
        return candidate
    # Roll to next month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    last_day = calendar.monthrange(year, month)[1]
    candidate = date(year, month, last_day)
    while candidate.weekday() != 3:
        candidate -= timedelta(days=1)
    return candidate


def _get_price_at(bars: list[dict], bar_time: time) -> float | None:
    """Latest close at or before bar_time."""
    price = None
    for bar in bars:
        if bar["time"] <= bar_time:
            price = bar["close"]
        else:
            break
    return price


def _lookup_price(
    option_bars: dict[tuple[str, float], list[dict]],
    opt_type: str,
    strike: float,
    bar_time: time,
) -> float | None:
    bars = option_bars.get((opt_type, strike))
    return _get_price_at(bars, bar_time) if bars else None


def _resolve_strike(
    leg_cfg: LegConfig,
    atm: float,
    step: int,
    spot: float,
    option_bars: dict[tuple[str, float], list[dict]],
    bar_time: time,
) -> float | None:
    opt_type = leg_cfg.type
    method = leg_cfg.strike_selection.method

    available = [k[1] for k in option_bars if k[0] == opt_type]
    if not available:
        return None

    if method == "atm_offset":
        target = atm + leg_cfg.strike_selection.offset * step
        return min(available, key=lambda s: abs(s - target))

    if method == "by_premium":
        target_prem = leg_cfg.strike_selection.target_premium or 0.0
        best, best_diff = None, float("inf")
        for strike in available:
            p = _lookup_price(option_bars, opt_type, strike, bar_time)
            if p is not None:
                diff = abs(p - target_prem)
                if diff < best_diff:
                    best_diff, best = diff, strike
        return best

    if method == "by_delta":
        # Delta not stored in option_bars — fall back to ATM-offset with warning
        log.warning("options_replay_delta_fallback", reason="delta not in option_bars")
        target = atm + leg_cfg.strike_selection.offset * step
        return min(available, key=lambda s: abs(s - target))

    return None


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------

class OptionsReplayEngine:
    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db

    def run(self, config: OptionsStrategyConfig) -> OptionsBacktestResult:
        settings = get_settings()
        comm_calc: Any = (
            CommissionCalculator(settings.backtest_commission)
            if config.commissions
            else NullCommissionCalculator(settings.backtest_commission)
        )

        step = _strike_step(config.underlying)
        entry_t = _parse_time(config.entry.time_ist)
        exit_t = _parse_time(config.exit.time_ist)
        from_date = config.date_range.from_
        to_date = config.date_range.to

        days = _biz_days_in_range(from_date, to_date)
        spot_by_day = self._load_spot_all(config.underlying, days)

        trade_log: list[TradeRecord] = []
        # (date, net_pnl, n_trades, n_reentries, last_exit_reason)
        daily: list[tuple[date, float, int, int, str]] = []
        total_comm = 0.0

        for d in days:
            spot_bars = spot_by_day.get(d)
            if not spot_bars:
                log.warning("options_replay_no_spot", date=str(d))
                continue

            expiry = _resolve_expiry(d, config.expiry_selection)
            opt_bars = self._load_option_bars(config.underlying, expiry, d)
            if not opt_bars:
                log.warning("options_replay_no_bars", date=str(d), expiry=str(expiry))
                continue

            res = self._replay_day(d, config, step, entry_t, exit_t, spot_bars, opt_bars, comm_calc)
            total_comm += res["commissions"]
            if res["n_trades"] > 0:
                daily.append((d, res["net_pnl"], res["n_trades"], res["n_reentries"], res["last_exit_reason"]))
                trade_log.extend(res["trades"])

        return _build_result(config, from_date, to_date, daily, trade_log, total_comm)

    # -----------------------------------------------------------------------
    # MongoDB loaders
    # -----------------------------------------------------------------------

    def _load_spot_all(self, underlying: str, days: list[date]) -> dict[date, list[dict]]:
        if not days:
            return {}
        _sid = {"NIFTY": "13", "BANKNIFTY": "25", "SENSEX": "51"}
        sid = _sid.get(underlying.upper(), "13")
        lo = datetime(days[0].year, days[0].month, days[0].day, tzinfo=UTC)
        hi = datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, tzinfo=UTC)
        cursor = self._db["market_bars"].find(
            {"metadata.security_id": sid, "ts": {"$gte": lo, "$lte": hi}},
            {"ts": 1, "close": 1, "_id": 0},
        )
        by_day: dict[date, list[dict]] = {}
        for doc in cursor:
            ts = doc["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            ist = ts + _IST
            t = ist.time().replace(second=0, microsecond=0)
            by_day.setdefault(ist.date(), []).append({"time": t, "close": float(doc["close"])})
        for v in by_day.values():
            v.sort(key=lambda b: b["time"])
        return by_day

    def _load_option_bars(
        self, underlying: str, expiry: date, trade_date: date
    ) -> dict[tuple[str, float], list[dict]]:
        expiry_dt = datetime(expiry.year, expiry.month, expiry.day, tzinfo=UTC)
        lo = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
        hi = datetime(trade_date.year, trade_date.month, trade_date.day, 23, 59, tzinfo=UTC)
        cursor = self._db["option_bars"].find(
            {
                "underlying": underlying,
                "expiry_date": expiry_dt,
                "timeframe": "1m",
                "ts": {"$gte": lo, "$lte": hi},
            },
            {"ts": 1, "close": 1, "strike": 1, "option_type": 1, "_id": 0},
        )
        bars: dict[tuple[str, float], list[dict]] = {}
        for doc in cursor:
            ts = doc["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            ist = ts + _IST
            t = ist.time().replace(second=0, microsecond=0)
            key = (doc["option_type"].upper(), float(doc["strike"]))
            bars.setdefault(key, []).append({"time": t, "close": float(doc["close"])})
        for v in bars.values():
            v.sort(key=lambda b: b["time"])
        return bars

    # -----------------------------------------------------------------------
    # Per-day replay
    # -----------------------------------------------------------------------

    def _replay_day(
        self,
        d: date,
        config: OptionsStrategyConfig,
        step: int,
        entry_t: time,
        exit_t: time,
        spot_bars: list[dict],
        opt_bars: dict[tuple[str, float], list[dict]],
        comm_calc: Any,
    ) -> dict:
        lot_size = config.lot_size
        risk = config.risk
        expiry = _resolve_expiry(d, config.expiry_selection)

        spot_by_time: dict[time, float] = {b["time"]: b["close"] for b in spot_bars}
        all_times = sorted(spot_by_time)

        pos: _Position | None = None
        trades: list[TradeRecord] = []
        gross_pnl = 0.0
        commissions = 0.0
        n_trades = 0
        n_reentries = 0
        entered = False

        for bar_time in all_times:
            if bar_time < entry_t:
                continue

            # Entry (first bar at or after entry_t)
            if not entered:
                spot = spot_by_time.get(bar_time)
                if spot is None:
                    continue
                atm = _atm(spot, step)
                legs, ok, comm = self._open_legs(
                    config, atm, step, spot, opt_bars, bar_time, expiry, lot_size, comm_calc
                )
                if not ok:
                    log.warning("options_replay_entry_failed", date=str(d))
                    break
                commissions += comm
                net_entry = sum(leg.entry_price * leg.config.lots for leg in legs)
                pos = _Position(legs=legs, net_entry_premium=net_entry)
                entered = True
                n_trades += 1
                continue

            if pos is None:
                break

            # Force exit
            if bar_time >= exit_t:
                comm, trade = self._close(pos, opt_bars, bar_time, lot_size, comm_calc, "time_exit", d)
                commissions += comm
                gross_pnl += trade.pnl
                trades.append(trade)
                pos = None
                break

            # Update prices
            for leg in pos.legs:
                p = _lookup_price(opt_bars, leg.config.type, leg.strike, bar_time)
                if p is not None:
                    leg.current_price = p

            combined = pos.combined_pnl()

            # Trailing SL update
            if risk.trailing_sl.enabled:
                pos.update_trailing(risk.trailing_sl.trail_after, risk.trailing_sl.trail_step)

            # Determine exit condition
            exit_reason: str | None = None
            if risk.combined_sl and combined <= -_sl_threshold(risk.combined_sl, pos.net_entry_premium):
                exit_reason = "combined_sl"
            elif (
                risk.trailing_sl.enabled
                and pos.trailing_sl_level is not None
                and combined <= pos.trailing_sl_level
            ):
                exit_reason = "trailing_sl"
            elif risk.combined_target and combined >= _sl_threshold(risk.combined_target, pos.net_entry_premium):
                exit_reason = "combined_target"
            if not exit_reason and risk.per_leg_sl:
                for leg in pos.legs:
                    leg_threshold = (
                        leg.entry_price * leg.config.lots * risk.per_leg_sl.value / 100.0
                        if risk.per_leg_sl.type == "percent"
                        else risk.per_leg_sl.value
                    )
                    if leg.pnl_points() <= -leg_threshold:
                        exit_reason = "per_leg_sl"
                        break

            if exit_reason:
                comm, trade = self._close(pos, opt_bars, bar_time, lot_size, comm_calc, exit_reason, d)
                commissions += comm
                gross_pnl += trade.pnl
                trades.append(trade)
                pos = None

                # Re-entry after SL
                can_reenter = (
                    exit_reason in ("combined_sl", "trailing_sl", "per_leg_sl")
                    and risk.re_entry.enabled
                    and n_reentries < risk.re_entry.max_count
                )
                if can_reenter:
                    spot = spot_by_time.get(bar_time)
                    if spot is not None:
                        atm = _atm(spot, step)
                        legs, ok, comm = self._open_legs(
                            config, atm, step, spot, opt_bars, bar_time, expiry, lot_size, comm_calc
                        )
                        if ok:
                            commissions += comm
                            n_reentries += 1
                            net_entry = sum(leg.entry_price * leg.config.lots for leg in legs)
                            pos = _Position(legs=legs, re_entry_count=n_reentries, net_entry_premium=net_entry)
                            n_trades += 1

        # End-of-day: close any remaining position
        if pos is not None and all_times:
            last_t = all_times[-1]
            comm, trade = self._close(pos, opt_bars, last_t, lot_size, comm_calc, "time_exit", d)
            commissions += comm
            gross_pnl += trade.pnl
            trades.append(trade)

        return {
            "net_pnl": gross_pnl - commissions,
            "n_trades": n_trades,
            "n_reentries": n_reentries,
            "trades": trades,
            "commissions": commissions,
            "last_exit_reason": trades[-1].exit_reason if trades else "",
        }

    def _open_legs(
        self,
        config: OptionsStrategyConfig,
        atm: float,
        step: int,
        spot: float,
        opt_bars: dict,
        bar_time: time,
        expiry: date,
        lot_size: int,
        comm_calc: Any,
    ) -> tuple[list[_LegState], bool, float]:
        legs: list[_LegState] = []
        total_comm = 0.0
        for leg_cfg in config.entry.legs:
            strike = _resolve_strike(leg_cfg, atm, step, spot, opt_bars, bar_time)
            if strike is None:
                return [], False, 0.0
            price = _lookup_price(opt_bars, leg_cfg.type, strike, bar_time)
            if price is None:
                return [], False, 0.0
            legs.append(_LegState(
                config=leg_cfg,
                strike=strike,
                expiry=expiry,
                entry_price=price,
                entry_time=bar_time.strftime("%H:%M"),
                current_price=price,
            ))
            turnover = Decimal(str(price * leg_cfg.lots * lot_size))
            comm = comm_calc.calculate(leg_cfg.side.lower(), turnover)
            total_comm += float(comm.total_inr)
        return legs, True, total_comm

    def _close(
        self,
        pos: _Position,
        opt_bars: dict,
        bar_time: time,
        lot_size: int,
        comm_calc: Any,
        exit_reason: str,
        d: date,
    ) -> tuple[float, TradeRecord]:
        t_str = bar_time.strftime("%H:%M")
        total_comm = 0.0
        for leg in pos.legs:
            price = _lookup_price(opt_bars, leg.config.type, leg.strike, bar_time)
            if price is None:
                price = leg.current_price
            leg.exit_price = price
            leg.exit_time = t_str
            leg.closed = True
            leg.current_price = price
            close_side = "buy" if leg.config.side == "SELL" else "sell"
            turnover = Decimal(str(price * leg.config.lots * lot_size))
            comm = comm_calc.calculate(close_side, turnover)
            total_comm += float(comm.total_inr)

        gross_inr = pos.combined_pnl() * lot_size
        entry_time = pos.legs[0].entry_time if pos.legs else ""
        trade = TradeRecord(
            date=d.isoformat(),
            entry_time=entry_time,
            exit_time=t_str,
            legs=[
                {
                    "type": leg.config.type,
                    "side": leg.config.side,
                    "strike": leg.strike,
                    "lots": leg.config.lots,
                    "entry_price": round(leg.entry_price, 2),
                    "exit_price": round(leg.exit_price, 2),
                    "pnl_points": round(leg.pnl_points(), 2),
                }
                for leg in pos.legs
            ],
            pnl=round(gross_inr, 2),
            exit_reason=exit_reason,
            re_entry_count=pos.re_entry_count,
        )
        return total_comm, trade


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _build_result(
    config: OptionsStrategyConfig,
    from_date: date,
    to_date: date,
    daily: list[tuple[date, float, int, int, str]],
    trade_log: list[TradeRecord],
    commissions_total: float,
) -> OptionsBacktestResult:
    total_pnl = sum(r[1] for r in daily)
    total_trades = sum(r[2] for r in daily)
    win_days = sum(1 for r in daily if r[1] > 0)
    win_rate = win_days / len(daily) if daily else 0.0

    # Equity curve + drawdown (single pass)
    equity_curve: list[dict] = []
    cumulative = 0.0
    running_peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for d, pnl, _, _, _ in daily:
        cumulative += pnl
        if cumulative > running_peak:
            running_peak = cumulative
        drawdown = cumulative - running_peak  # always ≤ 0
        dd = -drawdown
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / running_peak * 100) if running_peak > 0 else 0.0
        equity_curve.append({
            "date": d.isoformat(),
            "cumulative_pnl": round(cumulative, 2),
            "drawdown": round(drawdown, 2),
        })

    # Sharpe (annualised, daily P&L series)
    daily_pnls = [r[1] for r in daily]
    sharpe: float | None = None
    if len(daily_pnls) >= 2:
        avg = statistics.mean(daily_pnls)
        std = statistics.stdev(daily_pnls)
        if std > 0:
            sharpe = round((avg / std) * math.sqrt(252), 2)

    # Weekday stats
    weekday_data: dict[str, list[float]] = {}
    for d, pnl, _, _, _ in daily:
        wday = _WEEKDAY_NAMES[d.weekday()]
        weekday_data.setdefault(wday, []).append(pnl)
    weekday_stats = {
        wday.lower(): {
            "avg_pnl": round(statistics.mean(pnls), 2),
            "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 4),
            "count": len(pnls),
        }
        for wday, pnls in weekday_data.items()
    }

    daily_pnl_list = [
        {
            "date": d.isoformat(),
            "pnl": round(pnl, 2),
            "trades": n_trades,
            "re_entries": n_re,
            "weekday": _WEEKDAY_NAMES[d.weekday()],
            "exit_reason": exit_reason,
        }
        for d, pnl, n_trades, n_re, exit_reason in daily
    ]

    return OptionsBacktestResult(
        config_name=config.name,
        date_range=(from_date, to_date),
        total_pnl=round(total_pnl, 2),
        total_trades=total_trades,
        win_rate=round(win_rate, 4),
        max_drawdown=round(max_dd, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        sharpe_ratio=sharpe,
        equity_curve=equity_curve,
        daily_pnl=daily_pnl_list,
        weekday_stats=weekday_stats,
        trade_log=[
            {
                "date": t.date,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "legs": t.legs,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason,
                "re_entry_count": t.re_entry_count,
            }
            for t in trade_log
        ],
        commissions_total=round(commissions_total, 2),
    )
