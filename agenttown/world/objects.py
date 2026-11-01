"""Affordances: what an object lets an agent do, and what that does to it.

This table is the whole of Tier 0 "physics". Keeping effects declarative here
(rather than branching in the agent loop) is what lets the engine stay the
sole author of world state while the LLM only ever proposes an affordance name.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Affordance:
    name: str
    duration_ticks: int
    #: deltas applied on completion; needs are pressures, so negative relieves
    needs: dict[str, float] = field(default_factory=dict)
    #: key into economy.prices - the agent pays a vendor for it
    purchase: str | None = None
    #: earns the occupation wage for every tick spent on it
    wage: bool = False
    #: being here makes the agent available to converse
    social: bool = False
    #: worth writing into the memory stream when completed (observation gating)
    memorable: bool = True
    verb: str = "doing"


AFFORDANCES: dict[str, Affordance] = {
    "sleep": Affordance("sleep", 36, {"fatigue": -0.95, "mood": 0.05}, verb="sleeping"),
    "eat": Affordance("eat", 3, {"hunger": -0.5}, verb="eating at home"),
    "buy_bread": Affordance("buy_bread", 2, {"hunger": -0.45}, purchase="bread",
                            social=True, verb="buying bread"),
    "buy_coffee": Affordance("buy_coffee", 3, {"fatigue": -0.2, "loneliness": -0.25},
                             purchase="coffee", social=True, verb="having a coffee"),
    "buy_cigarettes": Affordance("buy_cigarettes", 2, {"mood": 0.08}, purchase="cigarettes",
                                 social=True, verb="buying cigarettes"),
    "buy_medicine": Affordance("buy_medicine", 3, {"mood": -0.05}, purchase="medicine",
                               verb="collecting medicine"),
    "work": Affordance("work", 6, {"fatigue": 0.09}, wage=True, social=True,
                       verb="working"),
    "study": Affordance("study", 6, {"fatigue": 0.06}, social=True, verb="in class"),
    "sit": Affordance("sit", 3, {"fatigue": -0.08}, memorable=False, social=True, verb="sitting"),
    "socialize": Affordance("socialize", 3, {"loneliness": -0.45, "mood": 0.06},
                            social=True, verb="talking"),
    "pray": Affordance("pray", 4, {"mood": 0.15, "loneliness": -0.15}, verb="praying"),
    "shop": Affordance("shop", 3, {"loneliness": -0.2}, social=True, verb="browsing the stalls"),
    "treat": Affordance("treat", 4, {"mood": 0.05}, verb="being seen by the nurse"),
    "vote": Affordance("vote", 2, {}, verb="voting"),
    "idle": Affordance("idle", 2, {}, memorable=False, social=True, verb="standing about"),
    "walk": Affordance("walk", 0, {}, memorable=False, verb="walking"),
}

#: affordances an LLM proposal is allowed to name
PROPOSABLE = tuple(sorted(k for k in AFFORDANCES if k not in ("walk",)))


def get(name: str) -> Affordance:
    return AFFORDANCES[name]


def exists(name: str) -> bool:
    return name in AFFORDANCES
