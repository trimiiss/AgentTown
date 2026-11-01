"""The Claude backend, tested offline against a scripted transport.

No network, no key, no spend - but it still pins down the things that actually
cost money or break a run: where the cache breakpoint sits, that the prefix is
byte-stable, that the schema is strict, and that every failure mode degrades to
the template backend instead of stopping the town.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agenttown.cognition.backend import (
    ConverseRequest,
    ImportanceRequest,
    PlanRequest,
    ReactRequest,
    ReflectRequest,
)
from agenttown.cognition.claude_backend import (
    ClaudeBackend,
    WireConversation,
    price_run,
    strict_schema,
)
from agenttown.cognition.mock_backend import MockBackend
from agenttown.cognition.schemas import Conversation, DailyPlan, Reaction

from .conftest import build


# --------------------------------------------------------------- fake client
def reply(payload: dict | str, stop_reason: str = "end_turn",
          category: str | None = None, usage: dict | None = None):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    u = {"input_tokens": 120, "output_tokens": 80,
         "cache_read_input_tokens": 400, "cache_creation_input_tokens": 0}
    u.update(usage or {})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(type="refusal", category=category)
        if category else None,
        usage=SimpleNamespace(**u),
    )


class FakeClient:
    """Records every request and returns scripted replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        nxt = self.replies.pop(0) if self.replies else reply({})
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def backend(*replies, seed: int = 1) -> tuple[ClaudeBackend, FakeClient]:
    client = FakeClient(*replies)
    return ClaudeBackend(seed, fallback=MockBackend(seed), client=client), client


# ------------------------------------------------------------- request shape
def plan_request(sim, agent_id: str = "agim") -> PlanRequest:
    from agenttown.cognition import prompts

    a = sim.agents[agent_id]
    req = PlanRequest(agent=a.brief(), tick=0, day=0, clock="07:00",
                      work_hours=a.work_hours,
                      prices=dict(sim.economy.prices),
                      memories=("I sold out of bread by nine.",))
    return replace(req, prompt=prompts.plan_prompt(req))


GOOD_PLAN = {"items": [
    {"start_hour": 4, "affordance": "work", "area": "furra", "note": "open up"},
    {"start_hour": 22, "affordance": "sleep", "area": "home_berisha", "note": ""},
]}


def test_the_stable_prefix_goes_in_system_behind_a_cache_breakpoint(sim):
    be, client = backend(reply(GOOD_PLAN))
    be.daily_plan(plan_request(sim))

    sent = client.requests[0]
    assert sent["model"] == "claude-haiku-5-5"
    system = sent["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["cache_control"] == {"type": "ephemeral"}

    head = system[0]["text"]
    tail = sent["messages"][0]["content"]
    # the run-constant things belong in the cached half
    assert "Agim Berisha" in head and "furra = " in head and "buy_bread" in head
    # and the volatile things must not leak into it
    assert "Money:" not in head and "Day 0" not in head
    assert "Money:" in tail


def test_the_cached_prefix_is_byte_identical_across_calls(sim):
    be, client = backend(reply(GOOD_PLAN), reply(GOOD_PLAN))
    be.daily_plan(plan_request(sim))
    sim.run(50)
    sim.agents["agim"].money += 99.0
    sim.agents["agim"].self_summary = "entirely different lately"
    be.daily_plan(plan_request(sim))

    first, second = (r["system"][0]["text"] for r in client.requests)
    assert first == second, "the cache prefix moved, so every call pays full price"


def test_effort_is_low_and_output_is_schema_constrained(sim):
    be, client = backend(reply(GOOD_PLAN))
    be.daily_plan(plan_request(sim))
    cfg = client.requests[0]["output_config"]
    assert cfg["effort"] == "low"
    assert cfg["format"]["type"] == "json_schema"
    schema = cfg["format"]["schema"]
    assert schema["additionalProperties"] is False


def test_strict_schema_requires_every_property_at_every_level():
    schema = strict_schema(WireConversation)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for defn in schema.get("$defs", {}).values():
        if defn.get("type") == "object":
            assert defn["additionalProperties"] is False
            assert set(defn["required"]) == set(defn["properties"])


# --------------------------------------------------------------- happy paths
def test_a_good_reply_becomes_a_domain_object(sim):
    be, _ = backend(reply(GOOD_PLAN))
    plan = be.daily_plan(plan_request(sim))
    assert isinstance(plan, DailyPlan)
    assert [i.affordance for i in plan.items] == ["work", "sleep"]
    assert plan.items[0].area == "furra"


def converse_request(sim) -> ConverseRequest:
    from agenttown.cognition import prompts

    a, b = sim.agents["agim"], sim.agents["fatime"]
    req = ConverseRequest(a=a.brief(b), b=b.brief(a), place="Furra", tick=5,
                          clock="08:00", max_turns=4,
                          a_memories=("Flour went up again.",),
                          b_memories=("Bread is dear.",),
                          prices=dict(sim.economy.prices))
    return replace(req, prompt=prompts.converse_prompt(req))


def test_conversation_and_gossip_are_mapped_back(sim):
    be, _ = backend(reply({
        "turns": [{"speaker": "agim", "text": "Flour is up, bre."},
                  {"speaker": "fatime", "text": "Everything is up."}],
        "sentiment": -0.3, "topic": "prices",
        "gossip_subject": "agim", "gossip_predicate": "has put up the price of",
        "gossip_object": "bread", "gossip_is_true": True,
    }))
    conv = be.converse(converse_request(sim))
    assert isinstance(conv, Conversation)
    assert [t.speaker for t in conv.turns] == ["agim", "fatime"]
    assert conv.gossip is not None and conv.gossip.subject == "agim"
    assert conv.sentiment == -0.3


def test_an_empty_gossip_predicate_means_no_rumour(sim):
    be, _ = backend(reply({
        "turns": [{"speaker": "agim", "text": "Cold today."}],
        "sentiment": 0.1, "topic": "smalltalk",
        "gossip_subject": "", "gossip_predicate": "", "gossip_object": "",
        "gossip_is_true": True,
    }))
    assert be.converse(converse_request(sim)).gossip is None


def test_turns_are_capped_at_max_turns(sim):
    be, _ = backend(reply({
        "turns": [{"speaker": "agim", "text": f"line {i}"} for i in range(9)],
        "sentiment": 0.0, "topic": "work",
        "gossip_subject": "", "gossip_predicate": "", "gossip_object": "",
        "gossip_is_true": True,
    }))
    assert len(be.converse(converse_request(sim)).turns) == 4


# ------------------------------------------------------- every failure mode
def react_request(sim) -> ReactRequest:
    from agenttown.cognition import prompts

    a = sim.agents["fatime"]
    req = ReactRequest(agent=a.brief(), tick=9, clock="09:00",
                       trigger="Bread is 0.95 now.", trigger_kind="price_change",
                       trigger_payload={"item": "bread"},
                       current_action="walking", memories=())
    return replace(req, prompt=prompts.react_prompt(req))


@pytest.mark.parametrize("scripted,expected_reason", [
    (reply({}, stop_reason="refusal", category="general_harms"), "refused"),
    (reply(GOOD_PLAN, stop_reason="max_tokens"), "truncated"),
    (reply("this is not json at all"), "unparseable"),
    (reply({"items": "not a list"}), "unparseable"),
])
def test_bad_replies_degrade_to_the_template_backend(sim, scripted, expected_reason):
    be, _ = backend(scripted)
    plan = be.daily_plan(plan_request(sim))
    assert isinstance(plan, DailyPlan) and plan.items, "the town stopped"
    assert any(expected_reason in d for d in be.degradations), be.degradations


def test_api_errors_degrade_and_are_classified(sim):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (anthropic.APIConnectionError(request=request), "network unreachable"),
        (anthropic.APITimeoutError(request=request), "timed out"),
        (RuntimeError("something odd"), "RuntimeError"),
    ]
    for exc, expected in cases:
        be, _ = backend(exc)
        plan = be.daily_plan(plan_request(sim))
        assert plan.items, "the town stopped"
        assert expected in be.degradations[-1], be.degradations


def test_a_hallucinated_affordance_drops_the_proposal_but_keeps_the_thought(sim):
    be, _ = backend(reply({
        "interrupt": True, "affordance": "teleport", "area": "furra",
        "reason": "because", "thought": "That price is a disgrace.",
    }))
    reaction = be.react(react_request(sim))
    assert isinstance(reaction, Reaction)
    assert reaction.interrupt is False and reaction.proposal is None
    assert reaction.thought == "That price is a disgrace."
    assert "bad affordance" in be.degradations[-1]


def test_skipped_importance_scores_fall_back_to_the_free_heuristic(sim):
    from agenttown.cognition import prompts

    items = ((1, "observation", "I walked to the shop"),
             (2, "observation", "Agim raised the price of bread"),
             (3, "dialogue", "She said there is an election"))
    req = ImportanceRequest(items=items)
    req = replace(req, prompt=prompts.importance_prompt(req))
    # the model answers for one memory, and invents an id that was not asked for
    be, _ = backend(reply({"ids": [2, 99], "scores": [8.0, 5.0]}))
    scores = be.score_importance(req).scores
    assert scores[2] == 8.0
    assert 99 not in scores, "an unrequested id leaked in"
    assert set(scores) == {1, 2, 3}
    assert scores[1] < scores[3]


def test_out_of_range_scores_are_clamped(sim):
    from agenttown.cognition import prompts

    req = ImportanceRequest(items=((1, "observation", "x"),))
    req = replace(req, prompt=prompts.importance_prompt(req))
    be, _ = backend(reply({"ids": [1], "scores": [93.0]}))
    assert be.score_importance(req).scores[1] == 10.0


# --------------------------------------------------------------- accounting
def test_usage_and_cache_ratio_come_from_the_response(sim):
    be, _ = backend(
        reply(GOOD_PLAN, usage={"input_tokens": 100, "output_tokens": 50,
                                "cache_read_input_tokens": 0,
                                "cache_creation_input_tokens": 900}),
        reply(GOOD_PLAN, usage={"input_tokens": 100, "output_tokens": 50,
                                "cache_read_input_tokens": 900,
                                "cache_creation_input_tokens": 0}),
    )
    be.daily_plan(plan_request(sim))
    be.daily_plan(plan_request(sim))
    assert be.usage == {"input": 200, "cache_read": 900,
                        "cache_write": 900, "output": 100}
    assert 0.4 < be.cache_hit_ratio < 0.5

    # The honest comparison: without caching, BOTH calls pay full price for the
    # 900-token prefix. A cache write costs 1.25x and a read 0.1x, so the
    # break-even is about two calls and everything after that is profit.
    cached = price_run(be.usage)
    uncached = price_run({"input": 2000, "cache_read": 0,
                          "cache_write": 0, "output": 100})
    assert cached < uncached, f"caching lost money: {cached} vs {uncached}"
    assert cached / uncached < 0.85


def test_a_failed_call_is_not_counted_as_a_call(sim):
    be, _ = backend(RuntimeError("boom"))
    be.daily_plan(plan_request(sim))
    assert be.calls == 0 and len(be.degradations) == 1


# ------------------------------------------------------- whole-simulation
def test_the_simulation_runs_on_the_claude_backend(cfg, day):
    """End to end on a scripted transport: no network, no spend."""
    sim = build(cfg)
    replies = [reply(GOOD_PLAN) for _ in range(400)]
    sim.backend = ClaudeBackend(cfg.sim.seed, fallback=sim.fallback,
                                client=FakeClient(*replies))
    try:
        sim.run(day)
        sim.inject("price_change", {"item": "bread", "to": 1.1})
        sim.run(30)

        assert sim.backend.calls > 0, "the backend was never reached"
        for a in sim.agents.values():
            assert sim.grid.is_walkable(a.x, a.y)
            assert a.money >= 0.0
        assert abs(sim.economy.imbalance(
            sim.agents.values(), sim.starting_money)) < 1e-6
        assert sim.snapshot()["agents"]
    finally:
        sim.close()


def test_a_backend_that_always_fails_still_leaves_a_working_town(cfg, day):
    sim = build(cfg)
    sim.backend = ClaudeBackend(
        cfg.sim.seed, fallback=sim.fallback,
        client=FakeClient(*[RuntimeError("down")] * 500))
    try:
        sim.run(day)
        assert sim.backend.calls == 0
        assert sim.backend.degradations, "failures were not recorded"
        assert all(a.plan for a in sim.agents.values()), "nobody got a plan"
        assert sum(1 for a in sim.agents.values() if a.insights) >= 0
    finally:
        sim.close()


def test_make_backend_resolves_claude_without_credentials(cfg):
    """Constructing the backend must not need a key - only calling it does."""
    import dataclasses

    from agenttown.sim.loop import make_backend

    claude_cfg = dataclasses.replace(
        cfg, cognition=dataclasses.replace(cfg.cognition, backend="claude"))
    be = make_backend(claude_cfg, MockBackend(1))
    assert be.name == "claude" and be.model == "claude-haiku-5-5"


def test_an_unknown_backend_name_fails_loudly(cfg):
    import dataclasses

    from agenttown.sim.loop import make_backend

    bad = dataclasses.replace(
        cfg, cognition=dataclasses.replace(cfg.cognition, backend="llama"))
    with pytest.raises(NotImplementedError, match="mock.*claude"):
        make_backend(bad, MockBackend(1))
