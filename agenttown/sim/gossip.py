"""Gossip as typed facts, so spread and decay can be measured.

A rumour is not free text: it is (subject, predicate, object, truth_value,
distortion). Each retelling increments distortion and may flip truth_value, so
you can watch a true thing become a false one as it crosses the town, and
count how many hops it took.
"""

from __future__ import annotations

from ..cognition.schemas import GossipItem

MAX_SHARE = 2          # how many items an agent will pass on in one conversation
STALE_AFTER = 1440     # ten sim-days: beyond this an item stops being news


def key_of(g: GossipItem | dict) -> str:
    if isinstance(g, GossipItem):
        return g.key()
    return f"{g.get('subject','')}|{g.get('predicate','')}|{g.get('object','')}"


def sentence(g: GossipItem | dict, name_of) -> str:
    if isinstance(g, GossipItem):
        subject, predicate, obj = g.subject, g.predicate, g.object
    else:
        subject = g.get("subject", "")
        predicate = g.get("predicate", "")
        obj = g.get("object", "")
    who = name_of(subject) if subject else "somebody"
    return f"{who} {predicate} {obj}".strip()


def to_record(g: GossipItem, tick: int, from_agent: str, name_of) -> dict:
    return {
        "key": g.key(), "subject": g.subject, "predicate": g.predicate,
        "object": g.object, "truth_value": g.truth_value,
        "distortion": g.distortion, "topic": g.topic,
        "learned_tick": tick, "from": from_agent,
        "sentence": sentence(g, name_of),
    }


def learn(agent, g: GossipItem, tick: int, from_agent: str, name_of) -> bool:
    """Record a rumour. True if it is news to this agent, or more distorted."""
    record = to_record(g, tick, from_agent, name_of)
    existing = agent.known_gossip.get(record["key"])
    if existing is not None and existing["distortion"] >= record["distortion"]:
        return False
    agent.known_gossip[record["key"]] = record
    return True


def shareable(agent, other, tick: int, limit: int = MAX_SHARE) -> list[dict]:
    """What this agent knows that the other has not heard, freshest first."""
    out = []
    for record in sorted(agent.known_gossip.values(),
                         key=lambda r: (-r["learned_tick"], r["key"])):
        if tick - record["learned_tick"] > STALE_AFTER:
            continue
        if record["key"] in other.known_gossip:
            continue
        if record.get("from") == other.id or record.get("subject") == other.id:
            continue          # do not tell someone their own rumour
        out.append(record)
        if len(out) >= limit:
            break
    return out


def spread_stats(agents) -> dict:
    """How far each rumour has travelled and how badly it has degraded."""
    carriers: dict[str, int] = {}
    worst: dict[str, int] = {}
    flipped: dict[str, bool] = {}
    text: dict[str, str] = {}
    for a in agents:
        for key, rec in a.known_gossip.items():
            carriers[key] = carriers.get(key, 0) + 1
            worst[key] = max(worst.get(key, 0), rec["distortion"])
            flipped[key] = flipped.get(key, False) or not rec["truth_value"]
            text.setdefault(key, rec["sentence"])
    items = [
        {"key": k, "sentence": text[k], "carriers": carriers[k],
         "max_distortion": worst[k], "went_false": flipped[k]}
        for k in carriers
    ]
    items.sort(key=lambda d: (-d["carriers"], d["key"]))
    return {"distinct": len(items), "items": items[:12]}
