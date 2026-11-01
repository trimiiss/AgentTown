"""The simulation loop: one tick at a time, deterministically.

Agents are always processed in sorted id order and every random draw is keyed
by (seed, who, when), so the outcome cannot depend on dict ordering or on how
the host schedules anything. That is what makes the replay test possible.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..agents import routines
from ..agents.agent import Agent
from ..cognition import prompts
from ..cognition.backend import (
    ConverseRequest,
    ImportanceRequest,
    PlanRequest,
    ReactRequest,
    ReflectRequest,
)
from ..cognition.budget import Budget
from ..cognition.mock_backend import MockBackend
from ..cognition.schemas import Validator
from ..config import Config
from ..memory.embed import HashedBowEmbedder
from ..memory.importance import is_ambiguous
from ..memory.retrieval import MemoryIndex
from ..memory.store import MemoryStore
from ..world import objects as aff_mod
from ..world.economy import Economy
from ..world.grid import Grid
from ..world.pathfind import Pathfinder
from . import gossip as gossip_mod
from .events import Event, EventBus, describe
from .recorder import Recorder
from .rng import stream

VIEW_RADIUS = 4
MAX_OBS_PER_DAY = 2            # per (affordance, area) - the observation gate
SIGHT_FORGET = 36              # re-notice people after six sim-hours
VENDOR_AREA = {"bread": "furra", "coffee": "kafiteria",
               "cigarettes": "dyqani", "medicine": "ambulanca"}


def make_backend(cfg: Config):
    """The cognition seam. Add claude/local here; nothing else changes."""
    name = cfg.cognition.backend
    if name == "mock":
        return MockBackend(cfg.sim.seed)
    raise NotImplementedError(
        f"backend {name!r} is not implemented yet - M3 adds claude and local. "
        "Set cognition.backend = 'mock' in config/sim.toml."
    )


class Simulation:
    def __init__(self, cfg: Config, record: bool = True,
                 run_name: str | None = None, in_memory_db: bool = False) -> None:
        self.cfg = cfg
        self.grid = Grid.load(cfg.town_path)
        self.pf = Pathfinder(self.grid)
        self.embedder = HashedBowEmbedder(cfg.memory.embed_dim)
        self.store = MemoryStore(
            ":memory:" if in_memory_db else cfg.db_path(),
            cfg.memory.embed_dim, fresh=True)
        self.index = MemoryIndex(self.store, self.embedder, cfg.retrieval,
                                 cfg.memory.working_set)

        spec = json.loads(Path(cfg.agents_path).read_text(encoding="utf-8"))
        self.agents: dict[str, Agent] = {}
        for d in spec["agents"]:
            rng = stream(cfg.sim.seed, "spawn", d["id"])
            self.agents[d["id"]] = Agent.from_config(d, self.grid, cfg, rng)
        self.order: list[str] = sorted(self.agents)

        vendors = {item: a.id for a in self.agents.values() for item in a.vendor_of}
        self.economy = Economy(prices=dict(cfg.economy.prices),
                               wages=dict(cfg.economy.wages), vendors=vendors)
        self.starting_money = self.economy.total_money(self.agents.values())

        self.backend = make_backend(cfg)
        self.fallback = MockBackend(cfg.sim.seed)
        self.budget = Budget(limits=dict(cfg.cognition.budget),
                             ticks_per_day=cfg.sim.ticks_per_day,
                             model=getattr(self.backend, "model", "mock"))
        self.validator = Validator(frozenset(self.grid.areas),
                                   frozenset(self.agents))
        self.cache = routines.PolicyCache()
        self.events = EventBus()

        path = None
        if record and cfg.recorder.enabled:
            name = run_name or f"run-{cfg.sim.seed}"
            path = cfg.recorder_dir() / f"{name}.jsonl"
        self.recorder = Recorder(path, enabled=path is not None)

        self.tick = -1
        self.paused = not cfg.sim.autostart
        self.conversations: list[dict] = []
        self.llm_log: list[dict] = []
        self.pending_speech: list[tuple[int, str, str]] = []
        self._obs_counter: dict[tuple, int] = {}
        self._pending_scores: list[tuple[int, str, str]] = []
        self.decisions_by_tier: dict[str, int] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def name_of(self, agent_id: str) -> str:
        a = self.agents.get(agent_id)
        return a.name if a else (agent_id or "somebody")

    def _remember(self, agent: Agent, kind: str, text: str, tick: int,
                  importance: float | None = None,
                  subjects: tuple[str, ...] = (), source: str | None = None):
        mem = self.index.add(agent.id, kind, text, tick, importance, subjects, source)
        agent.importance_accum += mem.importance
        if is_ambiguous(mem.importance):
            self._pending_scores.append((mem.id, mem.kind, mem.text))
        return mem

    def _obs_allowed(self, agent: Agent, day: int, affordance: str, area: str) -> bool:
        key = (agent.id, day, affordance, area)
        n = self._obs_counter.get(key, 0)
        if n >= MAX_OBS_PER_DAY:
            return False
        self._obs_counter[key] = n + 1
        return True

    def _call(self, call_type: str, req, batched: bool = False):
        """Budgeted dispatch. Exhaustion silently degrades to the mock."""
        allowed = self.budget.allow(call_type, max(self.tick, 0))
        backend = self.backend if allowed else self.fallback
        result = getattr(backend, call_type)(req)
        head, tail = prompts.split_cached(getattr(req, "prompt", ""))
        usd = self.budget.record(
            call_type,
            fresh_in=prompts.estimate_tokens(tail),
            cached_in=prompts.estimate_tokens(head),
            out=prompts.estimate_tokens(repr(result)),
            model=getattr(backend, "model", "mock"), batched=batched)
        self.llm_log.append({
            "tick": max(self.tick, 0), "call": call_type,
            "backend": backend.name, "degraded": not allowed,
            "usd": round(usd, 8),
        })
        del self.llm_log[:-400]
        return result

    def _retrieved(self, agent: Agent, query: str, tick: int, k: int) -> tuple[str, ...]:
        return tuple(s.memory.text
                     for s in self.index.retrieve(agent.id, query, tick, k=k))

    # ------------------------------------------------------------------
    # the tick
    # ------------------------------------------------------------------
    def step(self) -> dict:
        self.tick += 1
        t = self.tick
        day, hour = self.cfg.day_of(t), self.cfg.hour_of(t)

        self._apply_events(t)
        self._reveal_speech(t)
        self._plan_phase(t, day, hour)
        for aid in self.order:
            self._tick_agent(self.agents[aid], t, hour, day)
        self._social_phase(t)
        self._reflect_phase(t, day)
        self._score_phase(t)
        self.store.commit()
        return self._record(t, day)

    def run(self, ticks: int) -> dict:
        last: dict = {}
        for _ in range(ticks):
            last = self.step()
        return last

    # --- planning ------------------------------------------------------
    def _plan_phase(self, t: int, day: int, hour: int) -> None:
        for aid in self.order:
            a = self.agents[aid]
            if a.plan_day == day:
                continue
            if t != 0 and hour != self.cfg.sim.plan_hour:
                continue
            self._plan_for(a, t, day)

    def _plan_for(self, a: Agent, t: int, day: int) -> None:
        req = PlanRequest(
            agent=a.brief(), tick=t, day=day, clock=self.cfg.clock(t),
            work_hours=a.work_hours, prices=dict(self.economy.prices),
            memories=self._retrieved(a, "what matters for the day ahead", t, 6))
        req = replace(req, prompt=prompts.plan_prompt(req))
        plan = self.validator.plan(self._call("daily_plan", req, batched=True))
        a.plan, a.plan_day, a.plan_done = plan.items, day, set()
        if plan.items:
            summary = "; ".join(
                f"{p.start_hour:02d}:00 {p.affordance.replace('_', ' ')} "
                f"at {self.grid.areas[p.area].name}" for p in plan.items[:6])
            self._remember(a, "plan", f"Today I mean to: {summary}.", t)

    # --- per-agent physics --------------------------------------------
    def _tick_agent(self, a: Agent, t: int, hour: int, day: int) -> None:
        a.needs.tick(self.cfg.needs)

        if a.action is None:
            rng = stream(self.cfg.sim.seed, "decide", a.id, t)
            a.action = routines.decide(a, self.grid, self.cfg, t, hour,
                                       self.cache, rng, self._company_near(a))
            self.decisions_by_tier[a.action.tier] = \
                self.decisions_by_tier.get(a.action.tier, 0) + 1
            a.path = self.pf.path(a.pos, a.action.target)

        act = a.action
        if not act.arrived:
            if a.pos != act.target and not a.path:
                a.path = self.pf.path(a.pos, act.target)
                if not a.path:
                    a.action = None          # unreachable, pick again next tick
                    return
            for _ in range(self.cfg.sim.walk_speed):
                if a.pos == act.target or not a.path:
                    break
                a.x, a.y = a.path.pop(0)
            if a.pos == act.target:
                act.arrived = True
            self._track_area(a)
            if not act.arrived:
                return

        spec = aff_mod.AFFORDANCES.get(act.affordance, aff_mod.AFFORDANCES["idle"])
        if spec.wage and a.work == act.area:
            self.economy.pay_wage(a, t)
        act.ticks_left -= 1
        if act.ticks_left <= 0:
            self._complete(a, act, t, day)
            a.action = None

    def _track_area(self, a: Agent) -> None:
        here = self.grid.area_of(a.x, a.y)
        area_id = here.id if here else None
        if area_id != a.last_area:
            a.last_area = area_id
            a.seen_recently.clear()

    def _complete(self, a: Agent, act, t: int, day: int) -> None:
        spec = aff_mod.AFFORDANCES[act.affordance]
        paid = True
        if spec.purchase:
            paid = self.economy.purchase(a, spec.purchase, t, self.agents)
        if act.affordance == "eat":
            self.economy.consume(a, "bread")
        if paid:
            a.needs.apply(spec.needs)

        if not spec.memorable:
            return
        if not self._obs_allowed(a, day, act.affordance, act.area):
            return
        where = self.grid.areas[act.area].name
        if spec.purchase and paid:
            text = (f"I {spec.verb} at {where} and paid "
                    f"{self.economy.price(spec.purchase):.2f} euro.")
        elif spec.purchase:
            text = (f"I wanted {spec.purchase} at {where} but could not "
                    f"afford it.")
        else:
            text = f"I spent a while {spec.verb} at {where}."
        self._remember(a, "observation", text, t)

    def _company_near(self, a: Agent) -> bool:
        return any(o.id != a.id and abs(o.x - a.x) + abs(o.y - a.y) <= VIEW_RADIUS
                   for o in self.agents.values())

    # --- sightings and conversation ------------------------------------
    def _social_phase(self, t: int) -> None:
        conv_cfg = self.cfg.conversation
        for i, aid in enumerate(self.order):
            a = self.agents[aid]
            for bid in self.order[i + 1:]:
                b = self.agents[bid]
                if abs(a.x - b.x) + abs(a.y - b.y) > VIEW_RADIUS:
                    continue
                ra, rb = a.rel(b.id), b.rel(a.id)
                ra.on_sight(t)
                rb.on_sight(t)
                self._maybe_note_sighting(a, b, t)
                self._maybe_note_sighting(b, a, t)

                if not (self._available(a) and self._available(b)):
                    continue
                if not (ra.can_talk(t, conv_cfg.cooldown_ticks)
                        and rb.can_talk(t, conv_cfg.cooldown_ticks)):
                    continue
                lonely = max(a.needs.loneliness, b.needs.loneliness)
                if lonely < conv_cfg.min_social_need:
                    continue
                rng = stream(self.cfg.sim.seed, "meet", a.id, b.id, t)
                if rng.random() > 0.35 + 0.5 * lonely:
                    continue
                self._converse(a, b, t)

    def _available(self, a: Agent) -> bool:
        if a.action is None or not a.action.arrived:
            return False
        spec = aff_mod.AFFORDANCES.get(a.action.affordance)
        return bool(spec and spec.social)

    def _maybe_note_sighting(self, a: Agent, b: Agent, t: int) -> None:
        rel = a.rel(b.id)
        if b.id in a.seen_recently and t - rel.last_seen < SIGHT_FORGET:
            return
        a.seen_recently.add(b.id)
        if not self._available(a):
            return
        where = self.grid.area_name(a.x, a.y)
        self._remember(a, "observation", f"I saw {b.name} at {where}.", t,
                       subjects=(b.id,))

    def _converse(self, a: Agent, b: Agent, t: int) -> None:
        place = self.grid.area_name(a.x, a.y)
        share = gossip_mod.shareable(a, b, t)
        req = ConverseRequest(
            a=a.brief(b), b=b.brief(a), place=place, tick=t,
            clock=self.cfg.clock(t), max_turns=self.cfg.conversation.max_turns,
            a_memories=self._retrieved(a, f"{b.name} {place}", t, 5),
            b_memories=self._retrieved(b, f"{a.name} {place}", t, 5),
            a_gossip=tuple(share), prices=dict(self.economy.prices))
        req = replace(req, prompt=prompts.converse_prompt(req))
        conv = self.validator.conversation(self._call("converse", req),
                                           (a.id, b.id))
        if not conv.turns:
            return

        for n, u in enumerate(conv.turns):
            self.pending_speech.append((t + n * 2, u.speaker, u.text))

        transcript = " | ".join(f"{self.name_of(u.speaker)}: {u.text}"
                                for u in conv.turns)
        if len(transcript) > 200:
            transcript = transcript[:197].rsplit(" ", 1)[0] + "..."
        for me, them in ((a, b), (b, a)):
            self._remember(me, "dialogue",
                           f"I talked with {them.name} at {place}. {transcript}",
                           t, subjects=(them.id,))
            me.needs.apply({"loneliness": -0.35, "mood": 0.04 * conv.sentiment})
        a.rel(b.id).on_conversation(t, conv.sentiment)
        b.rel(a.id).on_conversation(t, conv.sentiment)

        for rec in share:
            from ..cognition.schemas import GossipItem
            item = GossipItem(subject=rec["subject"], predicate=rec["predicate"],
                              object=rec["object"],
                              truth_value=rec["truth_value"],
                              distortion=rec["distortion"], topic=rec["topic"])
            gossip_mod.learn(b, item, t, a.id, self.name_of)
        if conv.gossip is not None:
            for me, them in ((a, b), (b, a)):
                if gossip_mod.learn(me, conv.gossip, t, them.id, self.name_of):
                    self._remember(
                        me, "observation",
                        f"Word going round: {gossip_mod.sentence(conv.gossip, self.name_of)}.",
                        t, subjects=(conv.gossip.subject,) if conv.gossip.subject else ())

        self.conversations.append({
            "tick": t, "clock": self.cfg.clock(t), "place": place,
            "topic": conv.topic, "sentiment": round(conv.sentiment, 2),
            "a": a.id, "b": b.id,
            "turns": [{"speaker": u.speaker, "name": self.name_of(u.speaker),
                       "text": u.text} for u in conv.turns],
            "gossip": conv.gossip.model_dump() if conv.gossip else None,
        })
        del self.conversations[:-60]

    def _reveal_speech(self, t: int) -> None:
        """Stage conversation turns one at a time so it reads as back-and-forth."""
        still: list[tuple[int, str, str]] = []
        for due, aid, text in self.pending_speech:
            if due <= t:
                agent = self.agents.get(aid)
                if agent is not None:
                    agent.say(text, t, for_ticks=3)
            else:
                still.append((due, aid, text))
        self.pending_speech = still

    # --- reflection ----------------------------------------------------
    def _reflect_phase(self, t: int, day: int) -> None:
        for aid in self.order:
            a = self.agents[aid]
            if a.importance_accum < self.cfg.memory.reflection_threshold:
                continue
            req = ReflectRequest(
                agent=a.brief(), tick=t, day=day,
                memories=self._retrieved(a, "what has been happening to me", t, 12))
            req = replace(req, prompt=prompts.reflect_prompt(req))
            refl = self._call("reflect", req)
            for insight in refl.insights:
                self._remember(a, "reflection", insight, t)
            if refl.self_summary:
                a.self_summary = refl.self_summary
            a.insights.extend(refl.insights)
            del a.insights[:-20]
            a.importance_accum = 0.0
            a.last_reflection_tick = t

    # --- batched importance rescoring ----------------------------------
    def _score_phase(self, t: int) -> None:
        if len(self._pending_scores) < 12:
            return
        batch, self._pending_scores = tuple(self._pending_scores[:20]), \
            self._pending_scores[20:]
        req = ImportanceRequest(items=batch)
        req = replace(req, prompt=prompts.importance_prompt(req))
        result = self._call("score_importance", req, batched=True)
        clean = {int(k): max(1.0, min(10.0, float(v)))
                 for k, v in result.scores.items()}
        self.store.set_importance(clean)

    # --- events --------------------------------------------------------
    def inject(self, kind: str, payload: dict | None = None,
               scope: str = "town", importance: float = 8.0) -> Event:
        return self.events.inject(kind, payload, scope, max(self.tick, 0),
                                  importance=importance)

    def _scope_agents(self, scope: str) -> list[Agent]:
        if scope in ("town", "", None):
            return [self.agents[i] for i in self.order]
        if scope in self.agents:
            return [self.agents[scope]]
        if scope in self.grid.areas:
            area = self.grid.areas[scope]
            return [self.agents[i] for i in self.order
                    if area.contains(self.agents[i].x, self.agents[i].y)]
        return []

    def _apply_events(self, t: int) -> None:
        for ev in self.events.drain():
            ev.tick = t
            if ev.kind == "price_change":
                item = str(ev.payload.get("item", "bread"))
                if "to" in ev.payload:
                    old, new = self.economy.set_price(
                        item, ev.payload["to"], t, "event")
                else:
                    old, new = self.economy.adjust_price(
                        item, float(ev.payload.get("factor", 1.2)), t, "event")
                area = VENDOR_AREA.get(item, "")
                ev.payload.update({
                    "item": item, "from": old, "to": new,
                    "where": self.grid.areas[area].name if area else "the shop"})
                ev.text = describe(ev.kind, ev.payload)
                if area:
                    ev.payload["cache_invalidated"] = self.cache.invalidate_area(area)
            elif ev.kind == "remittance":
                for a in self._scope_agents(ev.scope):
                    self.economy.remit(a, float(ev.payload.get("amount", 50.0)),
                                       t, "from abroad")

            for a in self._scope_agents(ev.scope):
                self._remember(a, "observation", ev.text, t,
                               importance=ev.importance, source=f"event:{ev.id}")
                self._react(a, ev, t)

    def _react(self, a: Agent, ev: Event, t: int) -> None:
        current = (f"{a.action.affordance} at "
                   f"{self.grid.areas[a.action.area].name}") if a.action else "nothing"
        req = ReactRequest(
            agent=a.brief(), tick=t, clock=self.cfg.clock(t), trigger=ev.text,
            trigger_kind=ev.kind, trigger_payload=dict(ev.payload),
            current_action=current,
            memories=self._retrieved(a, ev.text, t, 5))
        req = replace(req, prompt=prompts.react_prompt(req))
        reaction = self._call("react", req)
        a.last_thought = reaction.thought
        if not reaction.interrupt:
            return
        proposal = self.validator.proposal(reaction.proposal)
        if proposal is None:
            return
        rng = stream(self.cfg.sim.seed, "react-act", a.id, t)
        a.action = routines.make_action(self.grid, proposal.affordance,
                                        proposal.area, rng,
                                        proposal.reason or "because of the news",
                                        "llm", t)
        self.decisions_by_tier["llm"] = self.decisions_by_tier.get("llm", 0) + 1
        a.path = self.pf.path(a.pos, a.action.target)

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------
    def _record(self, t: int, day: int) -> dict:
        payload = {
            "t": t, "day": day, "clock": self.cfg.clock(t),
            "agents": [
                {"id": a.id, "x": a.x, "y": a.y,
                 "act": a.action.affordance if a.action else None,
                 "tier": a.action.tier if a.action else None,
                 "money": round(a.money, 2),
                 "needs": a.needs.as_dict()}
                for a in (self.agents[i] for i in self.order)
            ],
            "events": [e["id"] for e in self.events.recent(5) if e["tick"] == t],
            "conversations": [c for c in self.conversations if c["tick"] == t],
            "prices": dict(self.economy.prices),
        }
        self.recorder.write(payload)
        return payload

    def snapshot(self) -> dict:
        t = max(self.tick, 0)
        return {
            "tick": t, "day": self.cfg.day_of(t), "clock": self.cfg.clock(t),
            "paused": self.paused,
            "agents": [self.agents[i].as_dict(t) for i in self.order],
            "conversations": self.conversations[-8:],
            "events": self.events.recent(8),
            "economy": self.economy.stats(self.agents.values(), self.starting_money),
            "budget": self.budget.stats(),
            "memory": self.index.stats(),
            "policy_cache": self.cache.stats(),
            "pathfinder": self.pf.stats(),
            "validator": self.validator.stats(),
            "decisions_by_tier": dict(sorted(self.decisions_by_tier.items())),
            "gossip": gossip_mod.spread_stats(
                [self.agents[i] for i in self.order]),
            "digest": self.recorder.digest,
            "ticks_logged": self.recorder.lines,
        }

    def detail(self, agent_id: str) -> dict:
        a = self.agents.get(agent_id)
        if a is None:
            return {}
        t = max(self.tick, 0)
        query = (f"{a.action.affordance} {self.grid.area_name(a.x, a.y)}"
                 if a.action else self.grid.area_name(a.x, a.y))
        out = a.detail(t)
        out["here"] = self.grid.area_name(a.x, a.y)
        out["retrieved"] = [s.as_dict()
                            for s in self.index.retrieve(a.id, query, t)]
        out["retrieval_query"] = query
        out["memory_count"] = self.store.count(a.id)
        out["working_set"] = self.index.working_set_size(a.id)
        out["prompt"] = prompts.identity_card(a.brief())
        return out

    def close(self) -> None:
        self.recorder.close()
        self.store.close()
