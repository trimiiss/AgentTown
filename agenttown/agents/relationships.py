"""Relationships: typed, engine-owned, and nudged by what actually happens."""

from __future__ import annotations

from dataclasses import dataclass

SIGHT_FAMILIARITY = 0.004
TALK_FAMILIARITY = 0.03
AFFINITY_RATE = 0.08


@dataclass
class Relationship:
    affinity: float = 0.0        # -1 hostile .. +1 close
    familiarity: float = 0.0     # 0 stranger .. 1 knows them well
    tag: str = ""
    last_seen: int = -1
    last_talked: int = -10_000
    conversations: int = 0

    def on_sight(self, tick: int) -> None:
        self.last_seen = tick
        self.familiarity = min(1.0, self.familiarity + SIGHT_FAMILIARITY)

    def on_conversation(self, tick: int, sentiment: float) -> None:
        self.last_talked = tick
        self.last_seen = tick
        self.conversations += 1
        self.familiarity = min(1.0, self.familiarity + TALK_FAMILIARITY)
        # a warm exchange pulls affinity up, a sour one drags it down
        self.affinity = max(-1.0, min(1.0, self.affinity + AFFINITY_RATE * sentiment))

    def can_talk(self, tick: int, cooldown: int) -> bool:
        return tick - self.last_talked >= cooldown

    def descriptor(self) -> str:
        if self.tag:
            return self.tag
        if self.familiarity < 0.15:
            return "barely known"
        if self.affinity > 0.5:
            return "a friend"
        if self.affinity < -0.3:
            return "someone he has fallen out with"
        return "an acquaintance"

    def as_dict(self) -> dict:
        return {"affinity": round(self.affinity, 3),
                "familiarity": round(self.familiarity, 3),
                "tag": self.tag, "last_seen": self.last_seen,
                "last_talked": self.last_talked,
                "conversations": self.conversations}
