"""Whole-simulation behaviour: observation gating, events, gossip, tiering."""

from __future__ import annotations


def test_observation_gating_keeps_memory_bounded(sim, day):
    """The gate exists to stop memory exploding, which is what kills retrieval.

    Writing an observation every tick would be ~144 per agent per sim-day.
    The bound here is deliberately loose: it catches an explosion and total
    silence, without pinning the figure to a number that was only ever an
    estimate. The measured value at the time of writing is ~13/agent/day.
    """
    days = 5
    for _ in range(day * days):
        sim.step()
    counts = sim.store.counts_by_agent()
    per_day = [counts.get(a, 0) / days for a in sim.order]
    assert min(per_day) > 4, f"agents are barely remembering anything: {per_day}"
    assert max(per_day) < 40, f"memory is exploding: {per_day}"


def test_most_decisions_never_reach_a_model(sim, day):
    for _ in range(day * 3):
        sim.step()
    tiers = sim.decisions_by_tier
    total = sum(tiers.values())
    assert total > 100
    assert tiers.get("llm", 0) / total < 0.05, tiers
    assert tiers.get("plan", 0) > 0, "the daily plan is never followed"


def test_policy_cache_warms_up(sim, day):
    for _ in range(day * 5):
        sim.step()
    assert sim.cache.hit_rate > 0.2, sim.cache.stats()


def test_llm_calls_stay_proportional_to_agents_not_ticks(sim, day):
    days = 4
    for _ in range(day * days):
        sim.step()
    per_agent_day = sim.budget.total.calls / days / len(sim.order)
    assert per_agent_day < 8, f"{per_agent_day:.1f} calls per agent per sim-day"


# ------------------------------------------------------------------- events
def test_price_change_is_felt_remembered_and_retrievable(sim, day):
    for _ in range(day):
        sim.step()
    assert sim.economy.price("bread") == 0.5

    sim.inject("price_change", {"item": "bread", "to": 0.95})
    sim.step()

    assert sim.economy.price("bread") == 0.95
    holders = retrievers = 0
    for aid in sim.order:
        held = [m for m in sim.store.for_agent(aid) if "price of bread" in m.text]
        if not held:
            continue
        holders += 1
        assert held[0].importance >= 6.0, "an injected event must land hard"
        top = sim.index.retrieve(aid, "the price of bread", sim.tick, k=5)
        retrievers += any("price of bread" in s.memory.text for s in top)
    assert holders == len(sim.order)
    assert retrievers == len(sim.order), "the news is held but never surfaces"


def test_price_change_invalidates_stale_habits(sim, day):
    for _ in range(day * 3):
        sim.step()
    assert sim.cache.store, "the cache never filled"
    ev = sim.inject("price_change", {"item": "bread", "to": 1.5})
    sim.step()
    assert ev.payload.get("cache_invalidated", 0) >= 0
    assert not any(area == "furra" for _aff, area in sim.cache.store.values())


def test_events_reach_only_their_scope(sim, day):
    for _ in range(day):
        sim.step()
    before = sim.store.count("agim")
    sim.inject("remittance", {"amount": 50.0}, scope="fatime")
    sim.step()
    assert sim.store.count("agim") == before
    assert any("abroad" in m.text for m in sim.store.for_agent("fatime"))
    assert sim.agents["fatime"].money > 0


def test_reaction_can_interrupt_the_current_action(sim, day):
    for _ in range(day * 2):
        sim.step()
    before = dict(sim.decisions_by_tier)
    sim.inject("election_called", {"when": "Sunday"})
    sim.step()
    after = sim.decisions_by_tier
    assert after.get("llm", 0) > before.get("llm", 0), \
        "no agent changed what it was doing"


def test_unknown_scope_is_a_no_op(sim):
    sim.step()
    before = sim.store.count()
    sim.inject("announcement", {"text": "hello"}, scope="atlantis")
    sim.step()
    assert sim.store.count() == before


# ------------------------------------------------------------------- gossip
def test_rumours_spread_and_degrade(sim, day):
    for _ in range(day * 8):
        sim.step()
    stats = sim.snapshot()["gossip"]
    assert stats["distinct"] > 0, "nobody gossiped in eight sim-days"
    best = max(stats["items"], key=lambda i: i["carriers"])
    assert best["carriers"] >= 2, "a rumour never left its author"
    assert max(i["max_distortion"] for i in stats["items"]) >= 1, \
        "rumours are being passed on verbatim"


def test_nobody_is_told_their_own_rumour(sim, day):
    for _ in range(day * 8):
        sim.step()
    for aid in sim.order:
        for rec in sim.agents[aid].known_gossip.values():
            assert rec["from"] != aid


# ---------------------------------------------------------------- reflection
def test_agents_reflect_and_keep_a_bounded_self_summary(sim, day):
    for _ in range(day * 4):
        sim.step()
    reflected = [a for a in sim.agents.values() if a.insights]
    assert reflected, "nobody reflected in four sim-days"
    for a in reflected:
        assert a.self_summary
        assert len(a.self_summary) < 900, "the self-summary is growing unbounded"
        assert len(a.insights) <= 20
        assert a.importance_accum < sim.cfg.memory.reflection_threshold


def test_reflections_are_stored_as_high_importance_memories(sim, day):
    for _ in range(day * 4):
        sim.step()
    found = [m for aid in sim.order
             for m in sim.store.for_agent(aid) if m.kind == "reflection"]
    assert found
    assert all(m.importance >= 6.0 for m in found)


# -------------------------------------------------------------------- output
def test_snapshot_and_detail_are_json_serialisable(sim, day):
    import json

    for _ in range(day):
        sim.step()
    json.dumps(sim.snapshot())
    for aid in sim.order:
        detail = json.dumps(sim.detail(aid))
        assert len(detail) > 100
    assert sim.detail("nobody") == {}
