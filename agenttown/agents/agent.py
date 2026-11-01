"""The agent: structured state the engine owns outright.

Money, position, inventory, relationships and needs are typed fields here, not
prose in a prompt. That is the first line of defence against an agent drifting
out of character over sim-days: the LLM can describe this state, and propose
changes to it, but never authors it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..cognition.backend import AgentBrief
from ..cognition.schemas import PlanItem
from ..config import Config
from ..world.grid import Grid
from .needs import Needs
from .relationships import Relationship

Point = tuple[int, int]


@dataclass
class Action:
    """What an agent is doing now, and which tier decided it."""

    affordance: str
    area: str
    target: Point
    object_id: str | None = None
    reason: str = ""
    tier: str = "reflex"          # reflex | policy | plan | need | llm
    ticks_left: int = 0
    arrived: bool = False
    started_tick: int = 0

    def as_dict(self) -> dict:
        return {"affordance": self.affordance, "area": self.area,
                "object": self.object_id, "reason": self.reason, "tier": self.tier,
                "ticks_left": self.ticks_left, "arrived": self.arrived}


@dataclass
class Agent:
    # --- immutable identity (the cached prompt prefix comes from this) ---
    id: str
    name: str
    age: int
    occupation: str
    traits: tuple[str, ...]
    speech_tics: tuple[str, ...]
    backstory: str
    home: str
    work: str | None
    vendor_of: tuple[str, ...]
    work_hours: tuple[int, int] | None
    faith: str

    # --- mutable world state (engine-owned) ---
    x: int = 0
    y: int = 0
    money: float = 0.0
    needs: Needs = field(default_factory=Needs)
    inventory: dict[str, int] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    opinion: dict[str, float] = field(default_factory=dict)

    # --- behaviour ---
    action: Action | None = None
    path: list[Point] = field(default_factory=list)
    plan: list[PlanItem] = field(default_factory=list)
    plan_day: int = -1
    plan_done: set[int] = field(default_factory=set)

    # --- cognition ---
    self_summary: str = ""
    insights: list[str] = field(default_factory=list)
    importance_accum: float = 0.0
    last_reflection_tick: int = -10_000
    known_gossip: dict[str, dict] = field(default_factory=dict)

    # --- observation gating state ---
    last_area: str | None = None
    seen_recently: set[str] = field(default_factory=set)

    # --- presentation ---
    speech: str = ""
    speech_until: int = -1
    last_thought: str = ""

    @property
    def pos(self) -> Point:
        return self.x, self.y

    # --- construction --------------------------------------------------
    @classmethod
    def from_config(cls, d: dict, grid: Grid, cfg: Config,
                    rng: random.Random) -> "Agent":
        wh = d.get("work_hours")
        agent = cls(
            id=d["id"], name=d["name"], age=int(d["age"]),
            occupation=d["occupation"],
            traits=tuple(d.get("traits", ())),
            speech_tics=tuple(d.get("speech_tics", ())),
            backstory=d.get("backstory", ""),
            home=d["home"], work=d.get("work"),
            vendor_of=tuple(d.get("vendor_of", ())),
            work_hours=(int(wh[0]), int(wh[1])) if wh else None,
            faith=d.get("faith", "muslim"),
            money=float(cfg.economy.starting_money),
            opinion=dict(d.get("opinion", {})),
        )
        agent.x, agent.y = grid.random_tile_in(agent.home, rng)
        for other, rel in d.get("relationships", {}).items():
            agent.relationships[other] = Relationship(
                affinity=float(rel.get("affinity", 0.0)),
                familiarity=float(rel.get("familiarity", 0.0)),
                tag=rel.get("tag", ""),
            )
        return agent

    # --- the cognition seam -------------------------------------------
    def rel(self, other_id: str) -> Relationship:
        if other_id not in self.relationships:
            self.relationships[other_id] = Relationship()
        return self.relationships[other_id]

    def brief(self, toward: "Agent | None" = None) -> AgentBrief:
        """Everything a backend may know. Built fresh so it cannot be mutated."""
        from ..cognition.prompts import identity_card

        tag, affinity = "", 0.0
        if toward is not None:
            r = self.relationships.get(toward.id)
            if r is not None:
                tag, affinity = r.descriptor(), r.affinity
        brief = AgentBrief(
            id=self.id, name=self.name, age=self.age, occupation=self.occupation,
            traits=self.traits, speech_tics=self.speech_tics,
            backstory=self.backstory, home=self.home, work=self.work,
            faith=self.faith, money=round(self.money, 2),
            needs=self.needs.as_dict(), vendor_of=self.vendor_of,
            identity_card="", self_summary=self.self_summary,
            political_lean=float(self.opinion.get("political_lean", 0.0)),
            relationship_tag=tag, affinity=round(affinity, 3),
        )
        # identity_card is derived, byte-stable, and therefore cacheable
        return AgentBrief(**{**brief.__dict__, "identity_card": identity_card(brief)})

    # --- presentation --------------------------------------------------
    def say(self, text: str, tick: int, for_ticks: int = 4) -> None:
        self.speech = text
        self.speech_until = tick + for_ticks

    def speaking(self, tick: int) -> str:
        return self.speech if tick <= self.speech_until else ""

    def as_dict(self, tick: int = 0) -> dict:
        return {
            "id": self.id, "name": self.name, "x": self.x, "y": self.y,
            "occupation": self.occupation,
            "action": self.action.as_dict() if self.action else None,
            "needs": self.needs.as_dict(), "money": round(self.money, 2),
            "speech": self.speaking(tick),
            "walking": bool(self.path),
        }

    def detail(self, tick: int) -> dict:
        return {
            "id": self.id, "name": self.name, "age": self.age,
            "occupation": self.occupation, "traits": list(self.traits),
            "speech_tics": list(self.speech_tics), "backstory": self.backstory,
            "home": self.home, "work": self.work, "faith": self.faith,
            "vendor_of": list(self.vendor_of),
            "work_hours": list(self.work_hours) if self.work_hours else None,
            "x": self.x, "y": self.y, "money": round(self.money, 2),
            "needs": self.needs.as_dict(), "inventory": dict(self.inventory),
            "opinion": {k: round(v, 3) for k, v in self.opinion.items()},
            "action": self.action.as_dict() if self.action else None,
            "plan": [
                {"start_hour": p.start_hour, "affordance": p.affordance,
                 "area": p.area, "note": p.note, "done": i in self.plan_done}
                for i, p in enumerate(self.plan)
            ],
            "self_summary": self.self_summary,
            "insights": self.insights[-6:],
            "importance_accum": round(self.importance_accum, 1),
            "relationships": {k: v.as_dict() for k, v in self.relationships.items()},
            "known_gossip": list(self.known_gossip.values()),
            "last_thought": self.last_thought,
            "speech": self.speaking(tick),
        }
