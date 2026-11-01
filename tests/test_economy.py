"""Money must be conserved except at declared sources and sinks.

The engine owns money outright, so if this invariant ever breaks it means some
code path is inventing or destroying value silently - which is exactly the
class of bug that makes a long simulation stop making sense.
"""

from __future__ import annotations


def test_conserved_across_a_week(sim, day):
    for _ in range(day * 7):
        sim.step()
    imbalance = sim.economy.imbalance(sim.agents.values(), sim.starting_money)
    assert abs(imbalance) < 1e-6, f"money imbalance {imbalance}"


def test_no_negative_balances(sim, day):
    for _ in range(day * 3):
        sim.step()
        for a in sim.agents.values():
            assert a.money >= 0.0, f"{a.id} is overdrawn at {a.money}"


def test_purchase_moves_money_rather_than_creating_it(sim):
    buyer = sim.agents["fatime"]
    vendor = sim.agents["agim"]          # the baker receives bread money
    before = buyer.money + vendor.money
    price = sim.economy.price("bread")
    assert sim.economy.purchase(buyer, "bread", 0, sim.agents) is True
    assert abs((buyer.money + vendor.money) - before) < 1e-9
    assert abs(vendor.money - (before - buyer.money)) < 1e-9
    assert buyer.inventory["bread"] == 1
    assert price > 0


def test_purchase_is_refused_when_broke_and_nothing_moves(sim):
    buyer = sim.agents["vlora"]
    vendor = sim.agents["agim"]
    buyer.money = 0.0
    before = vendor.money
    assert sim.economy.purchase(buyer, "bread", 0, sim.agents) is False
    assert buyer.money == 0.0 and vendor.money == before
    assert sim.economy.refusals == 1


def test_selling_to_yourself_is_a_no_op(sim):
    agim = sim.agents["agim"]
    before = agim.money
    assert sim.economy.purchase(agim, "bread", 0, sim.agents) is True
    assert abs(agim.money - before) < 1e-9


def test_a_price_change_is_one_world_variable(sim):
    assert sim.economy.price("bread") != 1.25
    old, new = sim.economy.set_price("bread", 1.25, tick=5, why="test")
    assert new == 1.25 and old != 1.25
    assert sim.economy.price_history[-1]["to"] == 1.25
    # and it is what the agents will actually be charged
    buyer = sim.agents["fatime"]
    buyer.money = 10.0
    sim.economy.purchase(buyer, "bread", 5, sim.agents)
    assert abs(buyer.money - 8.75) < 1e-9


def test_vendors_do_not_inflate_without_bound(sim, day):
    """Standing costs must keep the richest agent from running away."""
    for _ in range(day * 10):
        sim.step()
    assert sim.economy.sunk > 0.0, "no money is leaving the town"
    richest = max(a.money for a in sim.agents.values())
    assert richest < 40 * sim.cfg.economy.starting_money
