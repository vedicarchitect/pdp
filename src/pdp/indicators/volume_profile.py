"""Volume Profile indicator — price-bucketed session volume with POC/VAH/VAL (opt-in)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class VolumeProfileState:
    poc: float           # point of control (bucket centre with highest volume)
    vah: float           # value area high
    val: float           # value area low
    total_volume: float
    bucket_size: float
    session_date: date


class VolumeProfileTracker:
    """Session-anchored volume profile (opt-in, gated by explicit config request).

    Volume is accumulated into price buckets of ``bucket_size`` width using the bar's
    typical price.  The value area covers ``value_area_pct`` of total session volume
    (default 70 %).
    """

    __slots__ = ("_bucket_size", "_buckets", "_session_date", "_state", "_total_vol", "_va_pct")

    def __init__(self, bucket_size: float = 50.0, value_area_pct: float = 0.70) -> None:
        self._bucket_size = bucket_size
        self._va_pct = value_area_pct
        self._buckets: dict[int, float] = {}
        self._total_vol: float = 0.0
        self._session_date: date | None = None
        self._state: VolumeProfileState | None = None

    def _to_bucket(self, price: float) -> int:
        return int(price / self._bucket_size)

    def _from_bucket(self, bucket: int) -> float:
        return (bucket + 0.5) * self._bucket_size  # bucket centre

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> VolumeProfileState | None:
        session_date = bar_time.date() if bar_time is not None else None

        if session_date != self._session_date:
            self._buckets = {}
            self._total_vol = 0.0
            self._session_date = session_date

        if volume > 0:
            typical = (high + low + close) / 3.0
            bucket = self._to_bucket(typical)
            self._buckets[bucket] = self._buckets.get(bucket, 0.0) + volume
            self._total_vol += volume

        if not self._buckets:
            return None

        poc_bucket = max(self._buckets, key=lambda b: self._buckets[b])
        poc = self._from_bucket(poc_bucket)

        # Value area: greedily add highest-volume buckets until target volume covered
        target = self._total_vol * self._va_pct
        sorted_buckets = sorted(self._buckets, key=lambda b: self._buckets[b], reverse=True)
        covered = 0.0
        va_buckets: list[int] = []
        for b in sorted_buckets:
            covered += self._buckets[b]
            va_buckets.append(b)
            if covered >= target:
                break

        val = self._from_bucket(min(va_buckets))
        vah = self._from_bucket(max(va_buckets))

        self._state = VolumeProfileState(
            poc=poc, vah=vah, val=val,
            total_volume=self._total_vol,
            bucket_size=self._bucket_size,
            session_date=session_date,  # type: ignore[arg-type]
        )
        return self._state
