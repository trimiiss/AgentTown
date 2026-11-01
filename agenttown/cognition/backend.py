"""The cognition seam.

Five call types, no more. Everything else an agent does is Tier 0 or Tier 1 and
never reaches a model. A backend implementation receives only briefs and text -
never live world objects - so it cannot mutate the simulation, and so the mock,
Claude and local backends are genuinely interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .schemas import Conversation, DailyPlan, ImportanceScores, Reaction, Reflection

CALL_TYPES = ("daily_plan", "converse", "reflect", "react", "score_importance")


@dataclass(frozen=True)
class AgentBrief:
    """Everything a backend is allowed to know about an agent."""

    id: str
    name: str
    age: int
    occupation: str
    traits: tuple[str, ...]
    speech_tics: tuple[str, ...]
    backstory: str
    home: str
    work: str | None
    faith: str
    money: float
    needs: dict[str, float]
    vendor_of: tuple[str, ...]
    identity_card: str
    self_summary: str
    political_lean: float
    relationship_tag: str = ""
    affinity: float = 0.0


@dataclass(frozen=True)
class PlanRequest:
    agent: AgentBrief
    tick: int
    day: int
    clock: str
    work_hours: tuple[int, int] | None
    prices: dict[str, float]
    memories: tuple[str, ...]
    prompt: str = ""


@dataclass(frozen=True)
class ConverseRequest:
    a: AgentBrief
    b: AgentBrief
    place: str
    tick: int
    clock: str
    max_turns: int
    a_memories: tuple[str, ...]
    b_memories: tuple[str, ...]
    a_gossip: tuple[dict, ...] = ()
    prices: dict[str, float] = field(default_factory=dict)
    election_pending: bool = False
    candidates: tuple[str, ...] = ()
    prompt: str = ""


@dataclass(frozen=True)
class ReflectRequest:
    agent: AgentBrief
    tick: int
    day: int
    memories: tuple[str, ...]
    prompt: str = ""


@dataclass(frozen=True)
class ReactRequest:
    agent: AgentBrief
    tick: int
    clock: str
    trigger: str
    trigger_kind: str
    trigger_payload: dict
    current_action: str
    memories: tuple[str, ...]
    prompt: str = ""


@dataclass(frozen=True)
class ImportanceRequest:
    #: (memory id, kind, text) - batched, 10-20 at a time
    items: tuple[tuple[int, str, str], ...]
    prompt: str = ""


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def daily_plan(self, req: PlanRequest) -> DailyPlan: ...

    def converse(self, req: ConverseRequest) -> Conversation: ...

    def reflect(self, req: ReflectRequest) -> Reflection: ...

    def react(self, req: ReactRequest) -> Reaction: ...

    def score_importance(self, req: ImportanceRequest) -> ImportanceScores: ...
