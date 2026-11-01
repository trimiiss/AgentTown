"""Injected events.

Events have no special-case behaviour anywhere in the simulation. Injecting
one does exactly two things: it may write a world variable, and it writes a
high-importance observation into the memory streams of the agents in scope.
Reactions, conversations and reflections then follow from the ordinary rules -
which is why "the bakery raises prices" produces talk about bread without a
single line of bread-talk code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("price_change", "announcement", "election_called", "power_cut",
         "rumour", "arrival", "weather", "remittance")


@dataclass
class Event:
    kind: str
    payload: dict
    scope: str = "town"          # "town" | an area id | an agent id
    tick: int = 0
    text: str = ""
    importance: float = 8.0
    id: int = 0

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "payload": self.payload,
                "scope": self.scope, "tick": self.tick, "text": self.text,
                "importance": self.importance}


def describe(kind: str, payload: dict) -> str:
    """A sentence an agent could plausibly have overheard."""
    p = payload
    if kind == "price_change":
        item = p.get("item", "bread")
        to = p.get("to")
        where = p.get("where", "the shop")
        if to is not None:
            return f"The price of {item} at {where} has gone to {float(to):.2f} euro."
        return f"The price of {item} at {where} has changed."
    if kind == "election_called":
        return (f"An election has been called for "
                f"{p.get('when', 'next week')}.")
    if kind == "power_cut":
        return (f"The power is out across the town for about "
                f"{p.get('hours', 3)} hours.")
    if kind == "rumour":
        return f"People are saying {p.get('claim', 'something')}."
    if kind == "arrival":
        return f"{p.get('who', 'Somebody')} has arrived in town."
    if kind == "weather":
        return f"The weather has turned {p.get('to', 'cold')}."
    if kind == "remittance":
        return (f"Money came through from abroad for "
                f"{p.get('who', 'one of the families')}.")
    return str(p.get("text", "Something has happened in town."))


@dataclass
class EventBus:
    pending: list[Event] = field(default_factory=list)
    history: list[Event] = field(default_factory=list)
    _next_id: int = 1

    def inject(self, kind: str, payload: dict | None = None, scope: str = "town",
               tick: int = 0, text: str = "", importance: float = 8.0) -> Event:
        payload = dict(payload or {})
        ev = Event(kind=kind, payload=payload, scope=scope, tick=tick,
                   text=text or describe(kind, payload), importance=importance,
                   id=self._next_id)
        self._next_id += 1
        self.pending.append(ev)
        self.history.append(ev)
        return ev

    def drain(self) -> list[Event]:
        out, self.pending = self.pending, []
        return out

    def recent(self, n: int = 20) -> list[dict]:
        return [e.as_dict() for e in self.history[-n:]]

    @staticmethod
    def load_scenario(path: str | Path) -> list[dict]:
        """A scenario is just a list of events with optional tick offsets."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(data.get("events", []))
