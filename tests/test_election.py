"""The election: candidates, drift, turnout, the count.

The thing worth testing here is that none of it is scripted - support moves
because agents talk, turnout is earned rather than assumed, and the count is
derived from votes that were actually cast at the ballot box.
"""

from __future__ import annotations

import pytest

from agenttown.sim import election as election_mod
from agenttown.sim.election import LEAN, TALKS, Candidate, Election

from .conftest import build


# ------------------------------------------------------------------- units
def test_candidates_are_the_best_known_person_on_each_side(sim):
    candidates = election_mod.pick_candidates(sim.agents, sim.order)
    assert len(candidates) == 2
    leans = sorted(c.lean for c in candidates)
    assert leans[0] < 0 < leans[1], "both candidates sit on the same side"
    assert len({c.agent_id for c in candidates}) == 2


def test_candidates_can_be_named_explicitly(sim):
    picked = election_mod.pick_candidates(sim.agents, sim.order,
                                          ["blerim", "drita"])
    assert [c.agent_id for c in picked] == ["blerim", "drita"]
    assert all(c.platform for c in picked)


def test_a_town_of_one_opinion_still_gets_a_contest(sim):
    for a in sim.agents.values():
        a.opinion[LEAN] = 0.4
    picked = election_mod.pick_candidates(sim.agents, sim.order)
    assert len(picked) == 2


def test_voters_go_to_the_nearest_platform(sim):
    e = Election(0, 0, 5, [
        Candidate("left", "Left", -0.6, ""),
        Candidate("right", "Right", 0.6, ""),
    ])
    assert e.nearest(-0.9).agent_id == "left"
    assert e.nearest(0.2).agent_id == "right"


def test_a_warm_argument_converges_and_a_sour_one_polarises(sim):
    a, b = sim.agents["arben"], sim.agents["drita"]
    a.opinion[LEAN], b.opinion[LEAN] = 0.6, -0.6

    election_mod.drift_opinions(a, b, sentiment=0.8, familiarity=1.0)
    assert abs(a.opinion[LEAN] - b.opinion[LEAN]) < 1.2, "a good talk did not converge"

    a.opinion[LEAN], b.opinion[LEAN] = 0.3, -0.3
    before = abs(a.opinion[LEAN] - b.opinion[LEAN])
    election_mod.drift_opinions(a, b, sentiment=-0.8, familiarity=1.0)
    assert abs(a.opinion[LEAN] - b.opinion[LEAN]) > before, "a row did not polarise"


def test_drift_counts_political_conversations(sim):
    a, b = sim.agents["arben"], sim.agents["drita"]
    a.opinion.pop(TALKS, None)
    election_mod.drift_opinions(a, b, 0.1, 0.5)
    election_mod.drift_opinions(a, b, 0.1, 0.5)
    assert a.opinion[TALKS] == 2.0


def test_opinions_stay_in_range(sim):
    a, b = sim.agents["arben"], sim.agents["drita"]
    a.opinion[LEAN], b.opinion[LEAN] = 1.0, -1.0
    for _ in range(50):
        election_mod.drift_opinions(a, b, -1.0, 1.0)
    assert -1.0 <= a.opinion[LEAN] <= 1.0
    assert -1.0 <= b.opinion[LEAN] <= 1.0


def test_a_discredited_rumour_pushes_voters_away_from_its_subject(sim):
    listener = sim.agents["fatime"]
    listener.opinion[LEAN] = 0.0
    candidate = Candidate("blerim", "Blerim", 0.5, "")
    after = election_mod.damage_candidate(listener, candidate)
    assert after < 0.0, "the listener did not move away from the candidate"


def test_turnout_rises_with_conviction(sim):
    e = Election(0, 0, 3, [Candidate("x", "X", 0.0, "")])
    apathetic = sim.agents["nikolla"]
    apathetic.opinion.update({LEAN: 0.0, TALKS: 0.0})
    engaged = sim.agents["arben"]
    engaged.opinion.update({LEAN: 0.9, TALKS: 12.0})
    # chance is deterministic per (seed, agent, day); compare the probabilities
    assert e.will_vote(engaged, 1) or not e.will_vote(apathetic, 1)


def test_the_count_is_derived_and_a_tie_is_reported_as_one(sim):
    e = Election(0, 0, 1, [Candidate("a", "A", -0.5, ""),
                           Candidate("b", "B", 0.5, "")])
    e.votes = {"v1": "a", "v2": "b"}
    result = e.close(list(sim.agents.values()))
    assert result["winner"] is None and set(result["tied"]) == {"a", "b"}
    assert "dead heat" in e.headline()

    e2 = Election(0, 0, 1, [Candidate("a", "A", -0.5, ""),
                            Candidate("b", "B", 0.5, "")])
    e2.votes = {"v1": "a", "v2": "a", "v3": "b"}
    r2 = e2.close(list(sim.agents.values()))
    assert r2["winner"] == "a" and r2["tally"] == {"a": 2, "b": 1}
    assert "has won" in e2.headline()


def test_nobody_votes_twice_or_after_close(sim):
    e = Election(0, 0, 1, [Candidate("a", "A", 0.0, "")])
    voter = sim.agents["agim"]
    assert e.record_vote(voter) == "a"
    assert e.record_vote(voter) is None
    e.close(list(sim.agents.values()))
    assert e.record_vote(sim.agents["fatime"]) is None


# ------------------------------------------------------- whole simulation
@pytest.fixture
def voted(cfg, day):
    """Run a full campaign and election, and hand back the finished sim."""
    sim = build(cfg)
    sim.run(day * 3)
    sim.inject("election_called", {"in_days": 3, "when": "Sunday"})
    sim.run(day * 5)
    yield sim
    sim.close()


def test_an_election_runs_to_a_result(voted):
    e = voted.election
    assert e is not None and e.closed
    assert e.result["votes_cast"] > 0, "nobody voted"
    assert e.result["eligible"] == len(voted.order)
    assert 0.0 < e.result["turnout"] <= 1.0
    assert sum(e.result["tally"].values()) == e.result["votes_cast"]


def test_turnout_is_partial_because_it_is_earned(voted):
    assert voted.election.result["turnout"] < 1.0, "turnout cannot be total"
    assert voted.election.intending, "nobody even intended to vote"


def test_only_people_who_reached_the_ballot_box_are_counted(voted):
    e = voted.election
    assert e.result["votes_cast"] <= len(e.intending), \
        "more votes than people who meant to vote"


def test_voters_remember_voting(voted):
    remembered = [
        a.id for a in voted.agents.values()
        if any("I voted for" in m.text for m in voted.store.for_agent(a.id))
    ]
    assert len(remembered) == voted.election.result["votes_cast"]
    assert set(remembered) == set(voted.election.votes)


def test_the_campaign_dominates_conversation(voted):
    political = [c for c in voted.conversations if c["topic"] == "politics"]
    assert political, "an election was called and nobody discussed it"


def test_support_is_polled_each_day_and_moves(voted):
    polls = voted.election.polls
    assert len(polls) >= 3, "the campaign was never polled"
    assert [p["day"] for p in polls] == sorted({p["day"] for p in polls})
    totals = {sum(p["support"].values()) for p in polls}
    assert totals == {len(voted.order)}, "support does not account for everyone"
    assert len({p["polarisation"] for p in polls}) > 1, "opinion never moved"


def test_the_result_is_announced_to_the_whole_town(voted):
    headline = voted.election.headline()
    assert headline
    heard = sum(
        1 for a in voted.order
        if any(headline[:28] in m.text for m in voted.store.for_agent(a))
    )
    assert heard == len(voted.order), f"only {heard} residents heard the result"


def test_the_election_survives_a_failing_backend(cfg, day):
    """The vote must not depend on cognition succeeding."""
    from agenttown.cognition.claude_backend import ClaudeBackend

    from .test_claude_backend import FakeClient

    sim = build(cfg)
    sim.backend = ClaudeBackend(cfg.sim.seed, fallback=sim.fallback,
                                client=FakeClient(*[RuntimeError("down")] * 900))
    try:
        sim.run(day * 2)
        sim.inject("election_called", {"in_days": 2})
        sim.run(day * 4)
        assert sim.election.closed
        assert sim.election.result["votes_cast"] > 0
    finally:
        sim.close()


def test_snapshot_exposes_the_election_for_the_ui(voted):
    import json

    snap = voted.snapshot()
    e = snap["election"]
    json.dumps(snap)
    assert e["closed"] and e["result"]
    assert e["headline"]
    for candidate in e["candidates"]:
        assert set(candidate) == {"id", "name", "lean", "platform"}
    for poll in e["polls"]:
        assert set(poll) == {"day", "support", "mean_lean",
                             "polarisation", "spread"}


def test_no_election_means_a_null_field(sim):
    sim.run(20)
    assert sim.snapshot()["election"] is None
