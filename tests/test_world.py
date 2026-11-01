"""Pathfinding and the map: every place reachable, nobody standing in a wall."""

from __future__ import annotations

import itertools

from agenttown.world import objects as aff_mod


def test_every_area_reachable_from_every_other(sim):
    entrances = {a.id: a.entrance for a in sim.grid.areas.values()}
    unreachable = [
        (i, j) for i, j in itertools.permutations(entrances, 2)
        if not sim.pf.reachable(entrances[i], entrances[j])
    ]
    assert unreachable == []


def test_objects_are_reachable_and_inside_their_area(sim):
    street = sim.grid.areas["carshia"].entrance
    for o in sim.grid.objects.values():
        assert sim.grid.is_walkable(o.x, o.y), f"{o.id} sits on a wall"
        area = sim.grid.areas[o.area]
        assert area.contains(o.x, o.y), f"{o.id} is outside {o.area}"
        assert sim.pf.reachable(street, o.pos), f"{o.id} is unreachable"


def test_every_affordance_an_agent_can_propose_exists_somewhere(sim):
    """A proposable affordance with no object and no area is a dead end."""
    placed = set()
    for o in sim.grid.objects.values():
        placed.update(o.affordances)
    # these are resolved against an area rather than an object
    areaonly = {"socialize", "idle", "shop", "buy_bread", "buy_coffee",
                "buy_cigarettes", "buy_medicine"}
    missing = [a for a in aff_mod.PROPOSABLE
               if a not in placed and a not in areaonly]
    assert missing == []


def test_agents_never_occupy_a_wall(sim, day):
    for _ in range(day):
        sim.step()
        for a in sim.agents.values():
            assert sim.grid.is_walkable(a.x, a.y), \
                f"{a.id} is inside a wall at {a.x},{a.y}"
            assert 0 <= a.x < sim.grid.width and 0 <= a.y < sim.grid.height


def test_actions_always_target_a_real_area_and_walkable_tile(sim, day):
    for _ in range(day):
        sim.step()
        for a in sim.agents.values():
            if a.action is None:
                continue
            assert a.action.area in sim.grid.areas
            assert sim.grid.is_walkable(*a.action.target)


def test_path_cache_returns_equal_paths(sim):
    a = sim.grid.areas["furra"].entrance
    b = sim.grid.areas["komuna"].entrance
    first = sim.pf.path(a, b)
    second = sim.pf.path(a, b)
    assert first == second and len(first) > 0
    # the caller must not be able to corrupt the cache
    second.clear()
    assert sim.pf.path(a, b) == first
