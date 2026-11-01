"""Needs are pressures in 0..1 that rise every tick. Affordances relieve them.

mood is the exception: higher is better. Keeping all of this numeric and
engine-owned is what stops an LLM from quietly deciding an agent is no longer
hungry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import NeedsCfg

PRESSURES = ("hunger", "fatigue", "loneliness")


@dataclass
class Needs:
    hunger: float = 0.25
    fatigue: float = 0.25
    loneliness: float = 0.25
    mood: float = 0.60

    def tick(self, cfg: NeedsCfg) -> None:
        self.hunger = min(1.0, self.hunger + cfg.hunger_per_tick)
        self.fatigue = min(1.0, self.fatigue + cfg.fatigue_per_tick)
        self.loneliness = min(1.0, self.loneliness + cfg.loneliness_per_tick)
        # mood drifts toward neutral, dragged down by unmet pressure
        drag = 0.004 * (self.hunger + self.fatigue + self.loneliness)
        self.mood = max(0.0, min(1.0, self.mood + (0.5 - self.mood) * 0.004 - drag))

    def apply(self, deltas: dict[str, float]) -> None:
        for key, delta in deltas.items():
            current = getattr(self, key, None)
            if current is not None:
                setattr(self, key, max(0.0, min(1.0, current + delta)))

    def dominant(self, threshold: float) -> str | None:
        """The most urgent pressure over the threshold, or None."""
        worst, value = None, threshold
        for name in PRESSURES:
            v = getattr(self, name)
            if v > value:
                worst, value = name, v
        return worst

    def pressures(self) -> dict[str, float]:
        return {k: round(getattr(self, k), 3) for k in PRESSURES}

    def as_dict(self) -> dict[str, float]:
        return {"hunger": round(self.hunger, 3), "fatigue": round(self.fatigue, 3),
                "loneliness": round(self.loneliness, 3), "mood": round(self.mood, 3)}
