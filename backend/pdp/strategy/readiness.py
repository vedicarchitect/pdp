from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

State = Literal["ok", "degraded", "blocked"]


@dataclass(slots=True)
class ReadinessComponent:
    name: str
    state: State
    reason: str | None = None


@dataclass(slots=True)
class StrategyReadiness:
    state: State
    components: list[ReadinessComponent]

    @property
    def is_blocked(self) -> bool:
        return self.state == "blocked"

    @classmethod
    def evaluate(cls, components: list[ReadinessComponent]) -> StrategyReadiness:
        overall: State = "ok"
        for comp in components:
            if comp.state == "blocked":
                overall = "blocked"
                break
            elif comp.state == "degraded" and overall == "ok":
                overall = "degraded"
        return cls(state=overall, components=components)
