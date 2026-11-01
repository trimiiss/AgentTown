"""Prompt construction.

Built even under the mock backend, for three reasons: the inspector can show
exactly what a model would have been asked, M3 becomes a drop-in, and the
cache-prefix stability that makes Haiku cheap is testable today.

Layout is deliberate. The identity card is derived only from immutable seed
data, so it is byte-identical on every call for a given agent and can sit
behind a cache breakpoint. Everything volatile - clock, money, needs,
retrieved memories - comes after it and is never allowed to leak forward.
"""

from __future__ import annotations

from .backend import (
    AgentBrief,
    ConverseRequest,
    ImportanceRequest,
    PlanRequest,
    ReactRequest,
    ReflectRequest,
)

BREAKPOINT = "\n<<<CACHE_BREAKPOINT>>>\n"

SYSTEM = (
    "You are simulating one resident of a small town in Kosovo. "
    "Stay strictly in character. Answer only with the requested JSON. "
    "Never invent places or people that are not listed for you."
)


def identity_card(brief: AgentBrief) -> str:
    """Immutable. Byte-stable across a whole run - this is the cached prefix."""
    traits = ", ".join(brief.traits)
    tics = "; ".join(brief.speech_tics)
    work = brief.work or "no paid work"
    return (
        f"# {brief.name}\n"
        f"Age {brief.age}. Occupation: {brief.occupation}. Faith: {brief.faith}.\n"
        f"Lives at: {brief.home}. Works at: {work}.\n"
        f"Traits: {traits}.\n"
        f"Speech habits: {tics}.\n"
        f"History: {brief.backstory}"
    )


def _state_block(brief: AgentBrief, clock: str = "") -> str:
    needs = ", ".join(f"{k} {v:.2f}" for k, v in sorted(brief.needs.items()))
    lines = [f"Money: {brief.money:.2f} euro", f"Needs (0=fine, 1=urgent): {needs}"]
    if clock:
        lines.insert(0, f"Time: {clock}")
    if brief.self_summary:
        lines.append(f"Lately: {brief.self_summary}")
    return "\n".join(lines)


def _memories_block(memories: tuple[str, ...]) -> str:
    if not memories:
        return "Nothing in mind."
    return "\n".join(f"- {m}" for m in memories)


def plan_prompt(req: PlanRequest) -> str:
    hours = (f"{req.work_hours[0]:02d}:00-{req.work_hours[1]:02d}:00"
             if req.work_hours else "none")
    prices = ", ".join(f"{k} {v:.2f}" for k, v in sorted(req.prices.items()))
    return (
        f"{SYSTEM}\n\n{identity_card(req.agent)}{BREAKPOINT}"
        f"Day {req.day}. {_state_block(req.agent, req.clock)}\n"
        f"Your working hours: {hours}\nPrices today: {prices}\n\n"
        f"What you have been thinking about:\n{_memories_block(req.memories)}\n\n"
        "Plan your day as a list of {start_hour, affordance, area, note}."
    )


def converse_prompt(req: ConverseRequest) -> str:
    rel = req.b.relationship_tag or "an acquaintance"
    gossip = ("\n".join(f"- {g.get('sentence', '')}" for g in req.a_gossip)
              or "- nothing new")
    return (
        f"{SYSTEM}\n\n{identity_card(req.a)}{BREAKPOINT}"
        f"Time: {req.clock}. You are at {req.place}.\n"
        f"You meet {req.b.name} ({req.b.occupation}), who is {rel}. "
        f"Your feeling toward them: {req.a.affinity:+.2f}.\n"
        f"{_state_block(req.a)}\n\n"
        f"On your mind:\n{_memories_block(req.a_memories)}\n\n"
        f"News you could pass on:\n{gossip}\n\n"
        f"Write the whole exchange, at most {req.max_turns} turns, as "
        "{turns:[{speaker,text}], gossip, sentiment, topic}."
    )


def reflect_prompt(req: ReflectRequest) -> str:
    return (
        f"{SYSTEM}\n\n{identity_card(req.agent)}{BREAKPOINT}"
        f"Day {req.day}. {_state_block(req.agent)}\n\n"
        f"What has happened to you recently:\n{_memories_block(req.memories)}\n\n"
        "What are two or three higher-level things you now believe? "
        "Also rewrite who you have lately become, in at most 120 words. "
        "Answer as {insights:[...], self_summary:...}."
    )


def react_prompt(req: ReactRequest) -> str:
    return (
        f"{SYSTEM}\n\n{identity_card(req.agent)}{BREAKPOINT}"
        f"Time: {req.clock}. {_state_block(req.agent)}\n"
        f"You are currently: {req.current_action}\n\n"
        f"Something has happened: {req.trigger}\n\n"
        f"On your mind:\n{_memories_block(req.memories)}\n\n"
        "Do you drop what you are doing? Answer as "
        "{interrupt, proposal:{affordance,area,reason}, thought}."
    )


def importance_prompt(req: ImportanceRequest) -> str:
    items = "\n".join(f"{i}. [{kind}] {text}" for i, kind, text in req.items)
    return (
        f"{SYSTEM}{BREAKPOINT}"
        "Score how memorable each of these is for the person who experienced "
        "it, from 1 (utterly mundane) to 10 (life-changing).\n\n"
        f"{items}\n\nAnswer as {{scores:{{id:score}}}}."
    )


def estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token estimate, for the cost counter under mock."""
    return max(1, len(text) // 4)


def split_cached(prompt: str) -> tuple[str, str]:
    """The stable prefix and the volatile remainder."""
    if BREAKPOINT in prompt:
        head, tail = prompt.split(BREAKPOINT, 1)
        return head, tail
    return "", prompt
