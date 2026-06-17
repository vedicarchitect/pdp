"""Market Profile indicator — TPO-based developing profile per session (opt-in)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class MarketProfileState:
    poc: float                    # price level (bucket centre) with most TPO count
    tpo_counts: dict[int, int]    # bucket_index -> TPO count (snapshot copy)
    bucket_size: float
    session_date: date


class MarketProfileTracker:
    """Session-anchored TPO market profile (opt-in, gated by explicit config request).

    Each closed bar contributes one TPO count to every price bucket its range covers.
    The Profile Of Control (POC) is the bucket with the most TPOs.
    """

    __slots__ = ("_bucket_size", "_session_date", "_state", "_tpo_counts")

    def __init__(self, bucket_size: float = 50.0) -> None:
        self._bucket_size = bucket_size
        self._tpo_counts: dict[int, int] = {}
        self._session_date: date | None = None
        self._state: MarketProfileState | None = None

    def _to_bucket(self, price: float) -> int:
        return int(price / self._bucket_size)

    def _from_bucket(self, bucket: int) -> float:
        return (bucket + 0.5) * self._bucket_size

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> MarketProfileState | None:
        session_date = bar_time.date() if bar_time is not None else None

        if session_date != self._session_date:
            self._tpo_counts = {}
            self._session_date = session_date

        low_b = self._to_bucket(low)
        high_b = self._to_bucket(high)
        for b in range(low_b, high_b + 1):
            self._tpo_counts[b] = self._tpo_counts.get(b, 0) + 1

        if not self._tpo_counts:
            return None

        poc_bucket = max(self._tpo_counts, key=lambda b: self._tpo_counts[b])
        poc = self._from_bucket(poc_bucket)

        self._state = MarketProfileState(
            poc=poc,
            tpo_counts=dict(self._tpo_counts),
            bucket_size=self._bucket_size,
            session_date=session_date,  # type: ignore[arg-type]
        )
        return self._state
