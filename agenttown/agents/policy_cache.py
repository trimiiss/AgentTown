"""Tier 1: the policy cache.

Recurring plan-to-action generation is the single biggest cost in a naive
generative-agent simulation, because an agent faces almost the same situation
every morning. Here a decision is indexed by a coarse situation key, so an
agent pays for its first 07:00 and none of the ones after.

Keys are deliberately lossy. Too fine and nothing ever hits; too coarse and
agents stop responding to their own circumstances.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Key = tuple[str, int, str, str, bool]
Decision = tuple[str, str]      # (affordance, area)


@dataclass
class PolicyCache:
    store: dict[Key, Decision] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    writes: int = 0

    @staticmethod
    def key(occupation: str, hour: int, dominant_need: str | None,
            area_kind: str, company: bool) -> Key:
        return (occupation, hour // 3, dominant_need or "none", area_kind, company)

    def get(self, key: Key) -> Decision | None:
        hit = self.store.get(key)
        if hit is None:
            self.misses += 1
        else:
            self.hits += 1
        return hit

    def put(self, key: Key, decision: Decision) -> None:
        self.store[key] = decision
        self.writes += 1

    def invalidate_area(self, area: str) -> int:
        """Drop decisions that point at an area whose economics just changed."""
        stale = [k for k, (_aff, ar) in self.store.items() if ar == area]
        for k in stale:
            del self.store[k]
        return len(stale)

    def clear(self) -> None:
        self.store.clear()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict:
        return {"entries": len(self.store), "hits": self.hits,
                "misses": self.misses, "writes": self.writes,
                "hit_rate": round(self.hit_rate, 3)}
