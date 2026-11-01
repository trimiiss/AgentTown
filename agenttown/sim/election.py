"""The election: candidates, opinion drift, a real vote, a tally.

Like every other event, this adds no special-case path to the agent loop. An
`election_called` event sets a date and names candidates; after that the whole
thing runs on machinery that already existed:

* **opinion moves through conversation.** A warm political exchange pulls two
  people together, a sour one pushes them apart, so polarisation is something
  you watch rather than something that is configured.
* **rumours have consequences.** A rumour whose subject is a candidate, once it
  has turned false, costs that candidate support with whoever heard it.
* **voting is an affordance.** The komuna already had a ballot box with a
  `vote` affordance; agents walk there and use it like any other object.
* **turnout is emergent.** Whether an agent bothers depends on how strong their
  view is and how much politics they have actually talked about.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .rng import stream

#: how strongly one conversation moves an opinion
DRIFT = 0.07
#: how much a discredited rumour costs its subject
RUMOUR_DAMAGE = 0.05
#: pull back toward where a person started, so polarisation cannot saturate
ANCHOR = 0.04
LEAN = "political_lean"
TALKS = "political_talks"


def platform_for(lean: float) -> str:
    if lean > 0.35:
        return "jobs, the bypass road, and getting the factory reopened"
    if lean > 0.05:
        return "steady administration and no surprises"
    if lean < -0.35:
        return "the school, the clinic, and publishing the budget"
    return "fixing what is broken before promising anything new"


@dataclass
class Candidate:
    agent_id: str
    name: str
    lean: float
    platform: str

    def as_dict(self) -> dict:
        return {"id": self.agent_id, "name": self.name,
                "lean": round(self.lean, 3), "platform": self.platform}


@dataclass
class Election:
    called_tick: int
    called_day: int
    election_day: int
    candidates: list[Candidate]
    votes: dict[str, str] = field(default_factory=dict)   # voter -> candidate
    intending: set[str] = field(default_factory=set)
    closed: bool = False
    result: dict | None = None
    polls: list[dict] = field(default_factory=list)
    eligible: int = 0

    # --- lifecycle -----------------------------------------------------
    def pending(self, day: int) -> bool:
        return not self.closed and day <= self.election_day

    def is_polling_day(self, day: int) -> bool:
        return not self.closed and day == self.election_day

    def days_left(self, day: int) -> int:
        return max(0, self.election_day - day)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(c.agent_id for c in self.candidates)

    def is_candidate(self, agent_id: str) -> bool:
        return any(c.agent_id == agent_id for c in self.candidates)

    # --- opinion -------------------------------------------------------
    def nearest(self, lean: float) -> Candidate:
        return min(self.candidates, key=lambda c: abs(c.lean - lean))

    def support(self, agents) -> dict[str, int]:
        """Who each agent would vote for today, by nearest platform."""
        counts = {c.agent_id: 0 for c in self.candidates}
        for a in agents:
            counts[self.nearest(float(a.opinion.get(LEAN, 0.0))).agent_id] += 1
        return counts

    def take_poll(self, day: int, agents) -> dict:
        leans = [float(a.opinion.get(LEAN, 0.0)) for a in agents]
        # Polarisation is the standard deviation, not max-minus-min: with
        # thirty residents, two hardliners peg a max-minus-min measure at its
        # ceiling and it stops telling you anything.
        entry = {
            "day": day,
            "support": self.support(agents),
            "mean_lean": round(sum(leans) / max(1, len(leans)), 3),
            "polarisation": round(statistics.pstdev(leans), 3)
            if len(leans) > 1 else 0.0,
            "spread": round(max(leans) - min(leans), 3) if leans else 0.0,
        }
        # One point per day. The closing poll lands on a day that has usually
        # already been polled, and a time series must not carry two points at
        # the same x.
        if self.polls and self.polls[-1]["day"] == day:
            self.polls[-1] = entry
        else:
            self.polls.append(entry)
        del self.polls[:-60]
        return entry

    # --- voting --------------------------------------------------------
    def will_vote(self, agent, seed: int) -> bool:
        """Turnout is earned: a strong view or a lot of political talk."""
        lean = abs(float(agent.opinion.get(LEAN, 0.0)))
        talks = float(agent.opinion.get(TALKS, 0.0))
        chance = min(0.95, 0.30 + 0.45 * lean + 0.06 * talks)
        return stream(seed, "turnout", agent.id, self.election_day).random() < chance

    def record_vote(self, agent) -> str | None:
        if self.closed or agent.id in self.votes:
            return None
        choice = self.nearest(float(agent.opinion.get(LEAN, 0.0)))
        self.votes[agent.id] = choice.agent_id
        return choice.agent_id

    def close(self, agents) -> dict:
        tally = {c.agent_id: 0 for c in self.candidates}
        for candidate_id in self.votes.values():
            tally[candidate_id] = tally.get(candidate_id, 0) + 1
        self.eligible = len(list(agents))
        ranked = sorted(self.candidates,
                        key=lambda c: (-tally[c.agent_id], c.agent_id))
        top = tally[ranked[0].agent_id]
        drawn = [c for c in ranked if tally[c.agent_id] == top]
        self.closed = True
        self.result = {
            "tally": tally,
            "winner": None if len(drawn) > 1 else ranked[0].agent_id,
            "winner_name": None if len(drawn) > 1 else ranked[0].name,
            "tied": [c.agent_id for c in drawn] if len(drawn) > 1 else [],
            "votes_cast": len(self.votes),
            "eligible": self.eligible,
            "turnout": round(len(self.votes) / max(1, self.eligible), 3),
        }
        return self.result

    def headline(self) -> str:
        if not self.result:
            return ""
        r = self.result
        turnout = f"{round(100 * r['turnout'])}% of the town voted"
        if r["winner_name"]:
            return (f"{r['winner_name']} has won the election with "
                    f"{r['tally'][r['winner']]} votes. {turnout}.")
        names = ", ".join(c.name for c in self.candidates
                          if c.agent_id in r["tied"])
        return f"The election is a dead heat between {names}. {turnout}."

    def as_dict(self, day: int) -> dict:
        return {
            "called_day": self.called_day,
            "election_day": self.election_day,
            "days_left": self.days_left(day),
            "closed": self.closed,
            "candidates": [c.as_dict() for c in self.candidates],
            "intending": len(self.intending),
            "votes_cast": len(self.votes),
            "polls": self.polls,
            "result": self.result,
            "headline": self.headline(),
        }


# --------------------------------------------------------------------------
# selection and drift - both operate on ordinary agent state
# --------------------------------------------------------------------------
def pick_candidates(agents: dict, order: list[str],
                    named: list[str] | None = None) -> list[Candidate]:
    """The best-known person on each side of the argument stands.

    Deliberately not random: in a town this size the candidates are whoever
    everybody already has an opinion about.
    """
    def notoriety(agent_id: str) -> float:
        return sum(other.relationships[agent_id].familiarity
                   for other in agents.values()
                   if agent_id in other.relationships)

    if named:
        chosen = [agents[a] for a in named if a in agents]
    else:
        right = [a for a in (agents[i] for i in order)
                 if float(a.opinion.get(LEAN, 0.0)) > 0.05]
        left = [a for a in (agents[i] for i in order)
                if float(a.opinion.get(LEAN, 0.0)) < -0.05]
        chosen = []
        for pool in (right, left):
            if pool:
                chosen.append(max(pool, key=lambda a: (notoriety(a.id), a.id)))
        if len(chosen) < 2:                       # a town of one opinion
            rest = [a for a in (agents[i] for i in order) if a not in chosen]
            rest.sort(key=lambda a: (-notoriety(a.id), a.id))
            chosen.extend(rest[: 2 - len(chosen)])
    return [
        Candidate(agent_id=a.id, name=a.name,
                  lean=float(a.opinion.get(LEAN, 0.0)),
                  platform=platform_for(float(a.opinion.get(LEAN, 0.0))))
        for a in chosen
    ]


def drift_opinions(a, b, sentiment: float, familiarity: float) -> None:
    """A warm argument converges; a sour one polarises."""
    la = float(a.opinion.get(LEAN, 0.0))
    lb = float(b.opinion.get(LEAN, 0.0))
    pull = DRIFT * (0.5 + 0.5 * familiarity) * (1.0 if sentiment >= 0 else -1.0)
    for agent, mine, theirs in ((a, la, lb), (b, lb, la)):
        anchor = float(agent.opinion.get("lean_anchor", mine))
        moved = mine + pull * (theirs - mine) + ANCHOR * (anchor - mine)
        agent.opinion[LEAN] = max(-1.0, min(1.0, moved))
    for agent in (a, b):
        agent.opinion[TALKS] = float(agent.opinion.get(TALKS, 0.0)) + 1.0


def damage_candidate(listener, candidate: Candidate) -> float:
    """A discredited rumour pushes a listener away from its subject."""
    lean = float(listener.opinion.get(LEAN, 0.0))
    away = -1.0 if candidate.lean >= lean else 1.0
    listener.opinion[LEAN] = max(-1.0, min(1.0, lean + away * RUMOUR_DAMAGE))
    return listener.opinion[LEAN]
