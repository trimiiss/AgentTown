"""Prices, wages and transactions.

Prices are world variables, which is the whole trick behind event injection:
"the bakery raises prices" is a write to economy.prices["bread"] plus a
broadcast, not a special code path.

A purchase transfers money from buyer to vendor, so total money in the town is
conserved except at declared sources (wages, remittances) and sinks. That
invariant is what the economy test checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Transaction:
    tick: int
    kind: str                 # purchase | wage | remittance | refused
    buyer: str
    vendor: str | None
    item: str | None
    amount: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"tick": self.tick, "kind": self.kind, "buyer": self.buyer,
                "vendor": self.vendor, "item": self.item,
                "amount": round(self.amount, 2), "note": self.note}


@dataclass
class Economy:
    prices: dict[str, float]
    wages: dict[str, float]
    #: item -> agent id who receives the money
    vendors: dict[str, str] = field(default_factory=dict)
    ledger: list[Transaction] = field(default_factory=list)
    sourced: float = 0.0      # money created out of nothing (wages, remittances)
    sunk: float = 0.0         # money destroyed
    refusals: int = 0
    price_history: list[dict] = field(default_factory=list)

    # --- prices --------------------------------------------------------
    def price(self, item: str) -> float:
        return float(self.prices.get(item, 0.0))

    def set_price(self, item: str, value: float, tick: int = 0,
                  why: str = "") -> tuple[float, float]:
        old = self.price(item)
        self.prices[item] = round(max(0.0, float(value)), 2)
        self.price_history.append({"tick": tick, "item": item, "from": old,
                                   "to": self.prices[item], "why": why})
        return old, self.prices[item]

    def adjust_price(self, item: str, factor: float, tick: int = 0,
                     why: str = "") -> tuple[float, float]:
        return self.set_price(item, self.price(item) * factor, tick, why)

    # --- money movement ------------------------------------------------
    def wage_rate(self, occupation: str) -> float:
        return float(self.wages.get(occupation, 0.0))

    def pay_wage(self, agent, tick: int) -> float:
        """A source: wages enter the town from outside it."""
        rate = self.wage_rate(agent.occupation)
        if rate <= 0.0:
            return 0.0
        agent.money += rate
        self.sourced += rate
        return rate

    def remit(self, agent, amount: float, tick: int, note: str = "") -> float:
        agent.money += amount
        self.sourced += amount
        self.ledger.append(Transaction(tick, "remittance", agent.id, None,
                                       None, amount, note))
        return amount

    def purchase(self, buyer, item: str, tick: int,
                 vendor_of: dict[str, object] | None = None) -> bool:
        """Transfer the price from buyer to vendor. Conserving, or refused."""
        cost = self.price(item)
        if buyer.money < cost:
            self.refusals += 1
            self.ledger.append(Transaction(tick, "refused", buyer.id, None, item,
                                           cost, "cannot afford it"))
            return False
        vendor_id = self.vendors.get(item)
        buyer.money -= cost
        if vendor_id and vendor_id != buyer.id and vendor_of is not None:
            vendor = vendor_of.get(vendor_id)
            if vendor is not None:
                vendor.money += cost          # conserved: it moved, not vanished
            else:
                self.sunk += cost
        elif vendor_id == buyer.id:
            buyer.money += cost               # selling to yourself is a no-op
        else:
            self.sunk += cost
        buyer.inventory[item] = buyer.inventory.get(item, 0) + 1
        self.ledger.append(Transaction(tick, "purchase", buyer.id, vendor_id,
                                       item, cost))
        return True

    def consume(self, agent, item: str) -> bool:
        have = agent.inventory.get(item, 0)
        if have <= 0:
            return False
        agent.inventory[item] = have - 1
        return True

    # --- invariants ----------------------------------------------------
    def total_money(self, agents) -> float:
        return sum(a.money for a in agents)

    def expected_total(self, starting_total: float) -> float:
        return starting_total + self.sourced - self.sunk

    def imbalance(self, agents, starting_total: float) -> float:
        return self.total_money(agents) - self.expected_total(starting_total)

    def stats(self, agents, starting_total: float) -> dict:
        purchases = [t for t in self.ledger if t.kind == "purchase"]
        return {
            "prices": {k: round(v, 2) for k, v in sorted(self.prices.items())},
            "total_money": round(self.total_money(agents), 2),
            "sourced": round(self.sourced, 2),
            "sunk": round(self.sunk, 2),
            "imbalance": round(self.imbalance(agents, starting_total), 6),
            "purchases": len(purchases),
            "refusals": self.refusals,
            "price_changes": self.price_history[-5:],
        }
