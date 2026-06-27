"""Parse helpers + parsed config object for the EVENTS_* settings (mirrors instruments.snapshots)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    from pdp.settings import Settings

log = structlog.get_logger()


def _loads(raw: str, default: Any) -> Any:
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("events_config_parse_failed", raw=str(raw)[:80])
        return default
    return val


def _as_list(raw: str) -> list[Any]:
    val = _loads(raw, [])
    return cast("list[Any]", val) if isinstance(val, list) else []


def _as_dict(raw: str) -> dict[str, Any]:
    val = _loads(raw, {})
    return cast("dict[str, Any]", val) if isinstance(val, dict) else {}


def parse_timeframes(raw: str) -> list[str]:
    return [str(x) for x in _as_list(raw)]


def parse_ema_pairs(raw: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for item in _as_list(raw):
        if isinstance(item, (list, tuple)) and len(cast("list[Any]", item)) == 2:
            pair = cast("list[Any]", item)
            pairs.append((int(pair[0]), int(pair[1])))
    return pairs


def parse_int_list(raw: str) -> list[int]:
    return [int(x) for x in _as_list(raw)]


def parse_float_list(raw: str) -> list[float]:
    return [float(x) for x in _as_list(raw)]


def parse_levels(raw: str) -> dict[str, list[float]]:
    """{"NIFTY": [23600, 24000]} → {"NIFTY": [23600.0, 24000.0]}."""
    out: dict[str, list[float]] = {}
    for k, v in _as_dict(raw).items():
        if isinstance(v, list):
            out[str(k).upper()] = [float(x) for x in cast("list[Any]", v)]
    return out


def parse_ranges(raw: str) -> dict[str, tuple[float, float]]:
    """{"NIFTY:strangle": [23500, 24500]} → {"NIFTY:strangle": (23500.0, 24500.0)}."""
    out: dict[str, tuple[float, float]] = {}
    for k, v in _as_dict(raw).items():
        if isinstance(v, (list, tuple)) and len(cast("list[Any]", v)) == 2:
            pair = cast("list[Any]", v)
            out[str(k)] = (float(pair[0]), float(pair[1]))
    return out


def _empty_str_list() -> list[str]:
    return []


def _empty_pair_list() -> list[tuple[int, int]]:
    return []


def _empty_int_list() -> list[int]:
    return []


def _empty_float_list() -> list[float]:
    return []


def _empty_levels() -> dict[str, list[float]]:
    return {}


def _empty_ranges() -> dict[str, tuple[float, float]]:
    return {}


def _empty_str_set() -> set[str]:
    return set()


@dataclass
class EventConfig:
    """Parsed, typed view over the EVENTS_* settings (built once at startup)."""

    enabled: bool = True
    timeframes: list[str] = field(default_factory=_empty_str_list)
    ema_pairs: list[tuple[int, int]] = field(default_factory=_empty_pair_list)
    price_ema_periods: list[int] = field(default_factory=_empty_int_list)
    watch_levels: dict[str, list[float]] = field(default_factory=_empty_levels)
    position_ranges: dict[str, tuple[float, float]] = field(default_factory=_empty_ranges)
    proximity_band_pts: float = 30.0
    confluence_min: int = 2
    confluence_band_pts: float = 25.0
    otm_distance_pts: float = 100.0
    mtm_swing_inr: float = 5000.0
    trail_giveback_pct: float = 30.0
    oi_buildup_pct: float = 20.0
    oi_volume_spike_z: float = 3.0
    volume_spike_z: float = 3.0
    pcr_bands: list[float] = field(default_factory=_empty_float_list)
    gex_wall_pts: float = 50.0
    delta_neutral_band: float = 0.15
    gap_pct: float = 0.5
    stats_interval_seconds: int = 300
    position_sync_seconds: int = 30
    cooldown_seconds: int = 300
    push_enabled: bool = False
    push_min_severity: str = "WARNING"
    # event types explicitly disabled for push (mutable at runtime via PATCH /events/config)
    push_disabled_types: set[str] = field(default_factory=_empty_str_set)

    @classmethod
    def from_settings(cls, settings: Settings) -> EventConfig:
        return cls(
            enabled=settings.EVENTS_ENABLED,
            timeframes=parse_timeframes(settings.EVENTS_SPOT_TIMEFRAMES),
            ema_pairs=parse_ema_pairs(settings.EVENTS_EMA_PAIRS),
            price_ema_periods=parse_int_list(settings.EVENTS_PRICE_EMA_PERIODS),
            watch_levels=parse_levels(settings.EVENTS_WATCH_LEVELS),
            position_ranges=parse_ranges(settings.EVENTS_POSITION_RANGES),
            proximity_band_pts=settings.EVENTS_PROXIMITY_BAND_PTS,
            confluence_min=settings.EVENTS_CONFLUENCE_MIN,
            confluence_band_pts=settings.EVENTS_CONFLUENCE_BAND_PTS,
            otm_distance_pts=settings.EVENTS_OTM_DISTANCE_PTS,
            mtm_swing_inr=settings.EVENTS_MTM_SWING_INR,
            trail_giveback_pct=settings.EVENTS_TRAIL_GIVEBACK_PCT,
            oi_buildup_pct=settings.EVENTS_OI_BUILDUP_PCT,
            oi_volume_spike_z=settings.EVENTS_OI_VOLUME_SPIKE_Z,
            volume_spike_z=settings.EVENTS_VOLUME_SPIKE_Z,
            pcr_bands=parse_float_list(settings.EVENTS_PCR_BANDS),
            gex_wall_pts=settings.EVENTS_GEX_WALL_PTS,
            delta_neutral_band=settings.EVENTS_DELTA_NEUTRAL_BAND,
            gap_pct=settings.EVENTS_GAP_PCT,
            stats_interval_seconds=settings.EVENTS_STATS_INTERVAL_SECONDS,
            position_sync_seconds=settings.EVENTS_POSITION_SYNC_SECONDS,
            cooldown_seconds=settings.EVENTS_COOLDOWN_SECONDS,
            push_enabled=settings.EVENTS_PUSH_ENABLED,
            push_min_severity=settings.EVENTS_PUSH_MIN_SEVERITY,
        )
