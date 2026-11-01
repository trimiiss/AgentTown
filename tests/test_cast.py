"""The cast: twelve authored characters plus generated residents.

The checks that matter here are the ones that fail silently otherwise - an
occupation with no wage entry earns nothing and nobody notices for twenty
sim-days.
"""

from __future__ import annotations

import json

from .conftest import ROOT


def load(name: str) -> list[dict]:
    path = ROOT / "config" / name
    return json.loads(path.read_text(encoding="utf-8"))["agents"]


def test_cast_is_a_superset_of_the_authored_characters():
    authored = {a["id"]: a for a in load("agents.json")}
    cast = {a["id"]: a for a in load("cast.json")}
    assert len(authored) >= 12
    assert set(authored) <= set(cast)
    for agent_id, original in authored.items():
        # the generator must never rewrite a hand-authored character
        assert cast[agent_id]["backstory"] == original["backstory"]
        assert cast[agent_id]["traits"] == original["traits"]
        assert cast[agent_id]["occupation"] == original["occupation"]


def test_the_town_is_in_the_twenty_to_fifty_range():
    assert 20 <= len(load("cast.json")) <= 50


def test_every_occupation_has_a_wage_entry(cfg):
    """A missing wage silently means zero income, which is invisible for days."""
    missing = sorted({
        a["occupation"] for a in load("cast.json")
        if a["occupation"] not in cfg.economy.wages
    })
    assert missing == [], f"no wage configured for: {missing}"


def test_self_employed_live_on_their_margin_not_a_wage(cfg):
    """Paying a vendor a wage on top of a sales margin inflates them."""
    for agent in load("cast.json"):
        if agent["vendor_of"] and agent["occupation"] not in ("nurse",):
            assert cfg.economy.wages[agent["occupation"]] == 0.0, agent["id"]


def test_ids_homes_and_relationships_all_resolve():
    cast = load("cast.json")
    town = json.loads((ROOT / "config" / "town.json").read_text(encoding="utf-8"))
    areas = {a["id"] for a in town["areas"]}
    ids = [a["id"] for a in cast]
    assert len(ids) == len(set(ids)), "duplicate agent id"
    for a in cast:
        assert a["home"] in areas
        assert a["work"] is None or a["work"] in areas
        assert a["id"] not in a["relationships"], "related to themselves"
        for other in a["relationships"]:
            assert other in set(ids)


def test_households_form_rather_than_everyone_living_alone():
    homes: dict[str, int] = {}
    for a in load("cast.json"):
        homes[a["home"]] = homes.get(a["home"], 0) + 1
    assert max(homes.values()) >= 2, "nobody shares a house"
    assert max(homes.values()) <= 6, "a house is overcrowded"


def test_there_are_enough_homes_for_the_cast():
    town = json.loads((ROOT / "config" / "town.json").read_text(encoding="utf-8"))
    beds = [o for o in town["objects"] if "sleep" in o["affordances"]]
    homes = [a for a in town["areas"] if a["kind"] == "home"]
    assert len(homes) >= 10
    assert len(beds) >= len(homes), "a home with no bed cannot be slept in"


def test_the_whole_cast_runs_and_stays_consistent(sim, day):
    """Scale check: thirty agents, five sim-days, every invariant intact."""
    assert len(sim.order) >= 20
    for _ in range(day * 5):
        sim.step()

    assert abs(sim.economy.imbalance(sim.agents.values(), sim.starting_money)) < 1e-6
    assert sim.validator.stats()["total"] == 0
    for a in sim.agents.values():
        assert sim.grid.is_walkable(a.x, a.y)
        assert a.money >= 0.0
        assert a.plan, f"{a.id} never got a plan"
    # everybody should have met somebody by now
    assert all(a.relationships for a in sim.agents.values())
    assert sum(1 for a in sim.agents.values() if a.insights) > len(sim.order) // 2


def test_cost_per_sim_day_stays_in_cents_at_full_scale(sim, day):
    days = 5
    for _ in range(day * days):
        sim.step()
    tokens = sim.budget.stats()["tokens"]
    # claude-haiku-5-5: $0.10 fresh / $0.01 cached / $0.50 out per MTok
    usd_per_day = (tokens["fresh_in"] * 0.10 + tokens["cached_in"] * 0.01
                   + tokens["out"] * 0.50) / 1e6 / days
    assert usd_per_day < 0.05, f"${usd_per_day:.4f} per sim-day is too expensive"
