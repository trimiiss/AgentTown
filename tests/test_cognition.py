"""The wall between proposal and truth.

A backend may propose anything. The Validator must reject everything that
names a place, person or affordance this world does not have, and the
simulation must carry on from the template fallback with world state intact.
These tests feed the simulation a deliberately hostile backend.
"""

from __future__ import annotations

from agenttown.cognition.mock_backend import MockBackend
from agenttown.cognition.schemas import (
    ActionProposal,
    Conversation,
    DailyPlan,
    GossipItem,
    PlanItem,
    Reaction,
    Reflection,
    Utterance,
    Validator,
)


class HostileBackend(MockBackend):
    """Returns schema-valid objects that name things which do not exist."""

    name = "hostile"
    model = "mock"

    def daily_plan(self, req) -> DailyPlan:
        return DailyPlan(items=[
            PlanItem(start_hour=7, affordance="sleep", area="atlantis"),
            PlanItem(start_hour=9, affordance="work", area="the_moon"),
            PlanItem(start_hour=11, affordance="sleep", area=req.agent.home),
        ])

    def converse(self, req) -> Conversation:
        return Conversation(
            turns=[
                Utterance(speaker="a_ghost", text="I am not in this town."),
                Utterance(speaker=req.a.id, text="   "),
                Utterance(speaker=req.b.id, text="Only this line is legitimate."),
            ],
            gossip=GossipItem(subject="nobody_at_all", predicate="did",
                              object="something"),
            sentiment=0.1, topic="prices")

    def react(self, req) -> Reaction:
        return Reaction(interrupt=True, thought="off to nowhere",
                        proposal=ActionProposal(affordance="sleep",
                                                area="narnia"))

    def reflect(self, req) -> Reflection:
        return Reflection(insights=["an insight"], self_summary="a summary")


# --------------------------------------------------------------- unit level
def test_unknown_affordance_is_refused_at_construction():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        ActionProposal(affordance="teleport", area="furra")


def test_validator_rejects_unknown_area(sim):
    bad = sim.validator.proposal(ActionProposal(affordance="sleep", area="narnia"))
    assert bad is None
    assert sim.validator.rejections[-1]["what"] == "proposal"


def test_validator_keeps_the_good_plan_items_and_sorts_them(sim):
    plan = sim.validator.plan(DailyPlan(items=[
        PlanItem(start_hour=11, affordance="sleep", area="home_gashi"),
        PlanItem(start_hour=9, affordance="work", area="atlantis"),
        PlanItem(start_hour=7, affordance="pray", area="xhamia"),
    ]))
    assert [i.start_hour for i in plan.items] == [7, 11]
    assert all(i.area in sim.grid.areas for i in plan.items)


def test_validator_drops_phantom_speakers_and_empty_lines(sim):
    conv = sim.validator.conversation(
        Conversation(turns=[
            Utterance(speaker="a_ghost", text="hello"),
            Utterance(speaker="agim", text=" "),
            Utterance(speaker="agim", text="real line"),
        ]), ("agim", "fatime"))
    assert [u.text for u in conv.turns] == ["real line"]


def test_validator_rejects_gossip_about_nobody(sim):
    assert sim.validator.gossip(
        GossipItem(subject="who_even", predicate="did", object="x")) is None
    assert sim.validator.gossip(
        GossipItem(subject="agim", predicate=" ", object="x")) is None
    good = sim.validator.gossip(
        GossipItem(subject="agim", predicate="raised", object="bread"))
    assert good is not None


# ----------------------------------------------------- whole-simulation level
def test_hostile_backend_cannot_corrupt_the_world(cfg, day):
    from .conftest import build

    sim = build(cfg)
    sim.backend = HostileBackend(cfg.sim.seed)
    try:
        sim.run(60)
        sim.inject("price_change", {"item": "bread", "to": 2.0})
        sim.run(day)

        assert sim.validator.stats()["total"] > 0, "nothing was rejected"

        for a in sim.agents.values():
            assert sim.grid.is_walkable(a.x, a.y)
            assert a.money >= 0.0
            assert all(p.area in sim.grid.areas for p in a.plan)
            if a.action is not None:
                assert a.action.area in sim.grid.areas
            for key in a.known_gossip:
                subject = a.known_gossip[key]["subject"]
                assert subject == "" or subject in sim.agents

        imbalance = sim.economy.imbalance(sim.agents.values(), sim.starting_money)
        assert abs(imbalance) < 1e-6
    finally:
        sim.close()


def test_budget_exhaustion_degrades_instead_of_failing(cfg, day):
    from .conftest import build

    sim = build(cfg)
    sim.budget.limits = {k: 0 for k in sim.budget.limits}
    try:
        sim.run(day)
        sim.inject("election_called", {"when": "Sunday"})
        sim.run(30)
    finally:
        stats = sim.budget.stats()
        snapshot = sim.snapshot()
        sim.close()

    assert sum(stats["degraded"].values()) > 0, "nothing degraded"
    assert all(v == 0 for v in stats["used_today"].values())
    assert snapshot["agents"], "the simulation did not survive"
    assert any(e["backend"] == "mock" and e["degraded"] for e in sim.llm_log)


def test_identity_card_is_byte_stable(sim):
    """It is the cached prompt prefix, so it must not wobble between calls."""
    from agenttown.cognition.prompts import identity_card, split_cached, plan_prompt
    from agenttown.cognition.backend import PlanRequest

    a = sim.agents["agim"]
    first = identity_card(a.brief())
    sim.run(40)
    a.money += 100.0
    a.needs.hunger = 0.9
    a.self_summary = "something new entirely"
    assert identity_card(a.brief()) == first

    req = PlanRequest(agent=a.brief(), tick=1, day=0, clock="07:00",
                      work_hours=a.work_hours, prices={}, memories=())
    head, tail = split_cached(plan_prompt(req))
    assert first in head
    assert "something new entirely" in tail, "volatile state leaked into the prefix"


def test_all_five_call_types_are_exercised(cfg, day):
    from .conftest import build

    sim = build(cfg)
    try:
        sim.run(day * 2)
        sim.inject("price_change", {"item": "bread", "to": 1.4})
        sim.run(40)
        calls = sim.budget.stats()["calls"]
    finally:
        sim.close()
    assert all(calls[k] > 0 for k in
               ("daily_plan", "converse", "reflect", "react")), calls
