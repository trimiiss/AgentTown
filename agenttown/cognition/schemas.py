"""Typed shapes for everything cognition returns, plus the validator.

This module is the wall between proposal and truth. A backend - mock, Claude
or local - may only ever return these shapes, and the Validator rejects any
that name an affordance, place or person that does not exist in this world.
Hallucinated geography therefore cannot enter the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..world.objects import PROPOSABLE


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionProposal(Strict):
    affordance: str
    area: str
    reason: str = ""

    @field_validator("affordance")
    @classmethod
    def _known_affordance(cls, v: str) -> str:
        if v not in PROPOSABLE:
            raise ValueError(f"unknown affordance {v!r}")
        return v


class PlanItem(Strict):
    start_hour: int = Field(ge=0, le=23)
    affordance: str
    area: str
    note: str = ""


class DailyPlan(Strict):
    items: list[PlanItem] = Field(default_factory=list)


class Utterance(Strict):
    speaker: str
    text: str


class GossipItem(Strict):
    """A rumour as a typed fact, so spread and decay are measurable."""
    subject: str                 # agent id the claim is about ("" = the town)
    predicate: str               # short verb phrase
    object: str                  # what/whom
    truth_value: bool = True
    distortion: int = 0
    topic: str = "general"

    def sentence(self, name_of) -> str:
        who = name_of(self.subject) if self.subject else "someone"
        return f"{who} {self.predicate} {self.object}".strip()

    def key(self) -> str:
        return f"{self.subject}|{self.predicate}|{self.object}"


class Conversation(Strict):
    turns: list[Utterance] = Field(default_factory=list)
    gossip: GossipItem | None = None
    sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    topic: str = "general"


class Reflection(Strict):
    insights: list[str] = Field(default_factory=list)
    self_summary: str = ""


class Reaction(Strict):
    interrupt: bool = False
    proposal: ActionProposal | None = None
    thought: str = ""


class ImportanceScores(Strict):
    scores: dict[int, float] = Field(default_factory=dict)


@dataclass
class Validator:
    """Closed-world check. Anything it rejects is logged, never applied."""

    area_ids: frozenset[str]
    agent_ids: frozenset[str]
    rejections: list[dict] = field(default_factory=list)

    def _reject(self, what: str, why: str, payload: object) -> None:
        self.rejections.append({"what": what, "why": why, "payload": repr(payload)[:300]})

    def proposal(self, p: ActionProposal | None) -> ActionProposal | None:
        if p is None:
            return None
        if p.affordance not in PROPOSABLE:
            self._reject("proposal", f"unknown affordance {p.affordance!r}", p)
            return None
        if p.area not in self.area_ids:
            self._reject("proposal", f"unknown area {p.area!r}", p)
            return None
        return p

    def plan(self, plan: DailyPlan) -> DailyPlan:
        good: list[PlanItem] = []
        for item in plan.items:
            if item.affordance not in PROPOSABLE:
                self._reject("plan_item", f"unknown affordance {item.affordance!r}", item)
            elif item.area not in self.area_ids:
                self._reject("plan_item", f"unknown area {item.area!r}", item)
            else:
                good.append(item)
        good.sort(key=lambda i: i.start_hour)
        return DailyPlan(items=good)

    def gossip(self, g: GossipItem | None) -> GossipItem | None:
        if g is None:
            return None
        if g.subject and g.subject not in self.agent_ids:
            self._reject("gossip", f"unknown subject {g.subject!r}", g)
            return None
        if not g.predicate.strip():
            self._reject("gossip", "empty predicate", g)
            return None
        return g

    def conversation(self, c: Conversation, participants: tuple[str, str]) -> Conversation:
        turns = []
        for t in c.turns:
            if t.speaker not in participants:
                self._reject("utterance", f"speaker {t.speaker!r} not in conversation", t)
            elif not t.text.strip():
                self._reject("utterance", "empty text", t)
            else:
                turns.append(t)
        return Conversation(turns=turns, gossip=self.gossip(c.gossip),
                            sentiment=c.sentiment, topic=c.topic)

    def stats(self) -> dict:
        by: dict[str, int] = {}
        for r in self.rejections:
            by[r["what"]] = by.get(r["what"], 0) + 1
        return {"total": len(self.rejections), "by_kind": by,
                "recent": self.rejections[-5:]}
