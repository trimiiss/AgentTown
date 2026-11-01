"""Tiers 0 and 1: deciding what to do without a model.

Order of resolution, cheapest first:

  1. a pressing need  - sleep when exhausted, eat when hungry, seek company
  2. the daily plan   - the item whose hour has come
  3. the policy cache - what this agent did last time the situation looked
                        like this (Tier 1; a miss is what would escalate to
                        the LLM in a budgeted run)
  4. a default        - written back into the cache so it is free next time

Nothing here calls out. Over a sim-day the overwhelming majority of decisions
are answered by steps 1-3, which is the whole cost argument.
"""

from __future__ import annotations

import random

from ..config import Config
from ..world import objects as aff_mod
from ..world.grid import Grid
from .agent import Action, Agent
from .policy_cache import PolicyCache

SOCIAL_AREAS = ("kafiteria", "pazari", "parku", "carshia")


def _bread_source(agent: Agent) -> tuple[str, str]:
    """Where this agent gets fed, given what they sell."""
    if agent.inventory.get("bread", 0) > 0:
        return "eat", agent.home
    if "bread" in agent.vendor_of and agent.work:
        return "eat", agent.work          # the baker does not buy his own bread
    return "buy_bread", "furra"


def _need_action(agent: Agent, need: str, rng: random.Random) -> tuple[str, str]:
    if need == "fatigue":
        return "sleep", agent.home
    if need == "hunger":
        return _bread_source(agent)
    return "socialize", rng.choice(SOCIAL_AREAS)


def _default_action(agent: Agent, hour: int, rng: random.Random) -> tuple[str, str]:
    if hour >= 22 or hour < 6:
        return "sleep", agent.home
    if agent.work and agent.work_hours:
        h0, h1 = agent.work_hours
        working = (h0 <= hour < h1) if h0 <= h1 else (hour >= h0 or hour < h1)
        if working:
            return "work", agent.work
    if agent.occupation == "student" and 8 <= hour < 14:
        return "study", "shkolla"
    if rng.random() < 0.35:
        return "idle", "carshia"
    return rng.choice(("socialize", "shop", "idle")), rng.choice(SOCIAL_AREAS)


def _due_plan_index(agent: Agent, hour: int) -> int | None:
    """The latest plan item whose hour has arrived. Skipped items are retired."""
    due = [i for i, p in enumerate(agent.plan)
           if p.start_hour <= hour and i not in agent.plan_done]
    if not due:
        return None
    for i in due[:-1]:
        agent.plan_done.add(i)       # the morning is gone; do not chase it
    return due[-1]


def make_action(grid: Grid, affordance: str, area: str, rng: random.Random,
                reason: str, tier: str, tick: int) -> Action:
    """Resolve an (affordance, area) pair into a concrete, walkable action."""
    if area not in grid.areas:
        area = "carshia"
    obj = grid.object_in_area_with(area, affordance)
    target = obj.pos if obj else grid.random_tile_in(area, rng)
    if not grid.is_walkable(*target):
        target = grid.areas[area].entrance
    spec = aff_mod.AFFORDANCES.get(affordance, aff_mod.AFFORDANCES["idle"])
    return Action(affordance=affordance, area=area, target=target,
                  object_id=obj.id if obj else None, reason=reason, tier=tier,
                  ticks_left=spec.duration_ticks, started_tick=tick)


def decide(agent: Agent, grid: Grid, cfg: Config, tick: int, hour: int,
           cache: PolicyCache, rng: random.Random, company: bool) -> Action:
    urgent = agent.needs.dominant(cfg.needs.urgent_threshold)
    need = agent.needs.dominant(cfg.needs.act_threshold)
    here = grid.area_of(agent.x, agent.y)
    area_kind = here.kind if here else "street"

    # An urgent need overrides the plan. A merely pressing one does not - that
    # is what lets the day have a shape instead of collapsing into napping.
    if urgent is not None:
        affordance, area = _need_action(agent, urgent, rng)
        return make_action(grid, affordance, area, rng,
                           f"{urgent} will not wait", "need", tick)

    idx = _due_plan_index(agent, hour)
    if idx is not None:
        item = agent.plan[idx]
        agent.plan_done.add(idx)
        return make_action(grid, item.affordance, item.area, rng,
                           item.note or "as planned", "plan", tick)

    if need is not None:
        affordance, area = _need_action(agent, need, rng)
        return make_action(grid, affordance, area, rng,
                           f"{need} is getting hard to ignore", "need", tick)

    key = PolicyCache.key(agent.occupation, hour, need, area_kind, company)
    cached = cache.get(key)
    if cached is not None:
        return make_action(grid, cached[0], cached[1], rng,
                           "what I usually do at this hour", "policy", tick)

    affordance, area = _default_action(agent, hour, rng)
    cache.put(key, (affordance, area))
    return make_action(grid, affordance, area, rng, "nothing else pressing",
                       "reflex", tick)
