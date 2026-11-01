"""The Claude backend: real cognition behind the same five-call seam.

Three things make this cheap enough to run a town on:

* **the prefix is cached** - the world vocabulary and the agent identity card
  are byte-stable for a whole run, so they go in `system` behind a
  `cache_control` breakpoint and cost a tenth of their tokens after the first
  call. Everything volatile goes in the user turn, after the breakpoint.
* **effort is low** - these are short, in-character utterances, not reasoning
  problems. `output_config.effort` is the first lever before model choice.
* **structured output** - `output_config.format` means no parsing heuristics
  and no retries for malformed JSON.

And one thing makes it safe: **every failure degrades to the template backend**
rather than raising. An API error, a refusal, a timeout, a schema violation -
all of them fall through to the same mock the simulation was built on, so the
town keeps running. That is checked by a test.

The wire schemas below are deliberately flat and separate from
`cognition.schemas`. Strict structured output dislikes nullable nested objects,
so gossip is carried as three plain strings (an empty predicate means "no
gossip") and importance scores as two parallel lists rather than a dict with
integer keys. The mapping back to the internal domain types happens here, and
the result still goes through the ordinary Validator in the loop.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..memory.importance import heuristic_importance
from . import prompts
from .backend import (
    ConverseRequest,
    ImportanceRequest,
    PlanRequest,
    ReactRequest,
    ReflectRequest,
)
from .mock_backend import MockBackend
from .schemas import (
    ActionProposal,
    Conversation,
    DailyPlan,
    GossipItem,
    ImportanceScores,
    PlanItem,
    Reaction,
    Reflection,
    Utterance,
)

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 1024
EFFORT = "low"


# --------------------------------------------------------------------------
# wire schemas - flat on purpose, see the module docstring
# --------------------------------------------------------------------------
class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WirePlanItem(Wire):
    start_hour: int = Field(ge=0, le=23)
    affordance: str
    area: str
    note: str


class WirePlan(Wire):
    items: list[WirePlanItem]


class WireTurn(Wire):
    speaker: str
    text: str


class WireConversation(Wire):
    turns: list[WireTurn]
    sentiment: float = Field(ge=-1.0, le=1.0)
    topic: str
    #: an empty predicate means no rumour was passed
    gossip_subject: str
    gossip_predicate: str
    gossip_object: str
    gossip_is_true: bool


class WireReflection(Wire):
    insights: list[str]
    self_summary: str


class WireReaction(Wire):
    interrupt: bool
    affordance: str
    area: str
    reason: str
    thought: str


class WireScores(Wire):
    ids: list[int]
    scores: list[float]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema in the shape structured output wants.

    Every property required, no additional properties, at every level - a
    schema with optional fields is rejected in strict mode.
    """
    schema = model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = sorted(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for value in node:
                tighten(value)

    tighten(schema)
    for defn in schema.get("$defs", {}).values():
        tighten(defn)
    return schema


class ClaudeBackend:
    """Real cognition. Falls back to the template backend on any failure."""

    name = "claude"
    model = MODEL

    def __init__(self, seed: int, fallback: MockBackend | None = None,
                 model: str = MODEL, client: Any | None = None) -> None:
        self.model = model
        self.fallback = fallback or MockBackend(seed)
        self.calls = 0
        self.degradations: list[str] = []
        self.usage = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
        if client is not None:
            self.client = client
        else:
            try:
                import anthropic
            except ImportError as exc:                     # pragma: no cover
                raise RuntimeError(
                    "the claude backend needs the anthropic SDK: uv add anthropic"
                ) from exc
            # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an
            # `ant auth login` profile - never hardcode a key.
            self.client = anthropic.Anthropic(max_retries=2, timeout=30.0)

    # ------------------------------------------------------------------
    def _note(self, call_type: str, why: str) -> None:
        self.degradations.append(f"{call_type}: {why}")
        del self.degradations[:-50]

    def _ask(self, call_type: str, prompt: str,
             schema: type[BaseModel]) -> BaseModel | None:
        """One request. Returns None on any failure, which means "use mock"."""
        cached, volatile = prompts.split_cached(prompt)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                # the stable prefix, behind a cache breakpoint
                system=[{
                    "type": "text",
                    "text": cached,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": volatile}],
                output_config={
                    "effort": EFFORT,
                    "format": {
                        "type": "json_schema",
                        "schema": strict_schema(schema),
                    },
                },
            )
        except Exception as exc:                 # noqa: BLE001 - see below
            # Deliberately broad. A backend that raises stops the town; a
            # backend that returns None degrades it. The typed chain lives in
            # _classify so the reason is still recorded accurately.
            self._note(call_type, _classify(exc))
            return None

        self.calls += 1
        self._record_usage(response)

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            self._note(call_type,
                       f"refused ({getattr(details, 'category', 'unknown')})")
            return None
        if getattr(response, "stop_reason", None) == "max_tokens":
            self._note(call_type, "truncated at max_tokens")
            return None

        try:
            text = next(b.text for b in response.content
                        if getattr(b, "type", None) == "text")
            return schema.model_validate_json(text)
        except Exception as exc:                 # noqa: BLE001
            self._note(call_type, f"unparseable output ({type(exc).__name__})")
            return None

    def _record_usage(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            return
        self.usage["input"] += getattr(u, "input_tokens", 0) or 0
        self.usage["output"] += getattr(u, "output_tokens", 0) or 0
        self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.usage["cache_write"] += (
            getattr(u, "cache_creation_input_tokens", 0) or 0)

    @property
    def cache_hit_ratio(self) -> float:
        read = self.usage["cache_read"]
        total = read + self.usage["input"] + self.usage["cache_write"]
        return read / total if total else 0.0

    # ------------------------------------------------------------------
    # the five call types
    # ------------------------------------------------------------------
    def daily_plan(self, req: PlanRequest) -> DailyPlan:
        wire = self._ask("daily_plan", req.prompt, WirePlan)
        if wire is None:
            return self.fallback.daily_plan(req)
        return DailyPlan(items=[
            PlanItem(start_hour=i.start_hour, affordance=i.affordance,
                     area=i.area, note=i.note)
            for i in wire.items
        ])

    def converse(self, req: ConverseRequest) -> Conversation:
        wire = self._ask("converse", req.prompt, WireConversation)
        if wire is None:
            return self.fallback.converse(req)
        gossip = None
        if wire.gossip_predicate.strip():
            gossip = GossipItem(
                subject=wire.gossip_subject, predicate=wire.gossip_predicate,
                object=wire.gossip_object, truth_value=wire.gossip_is_true,
                distortion=int(req.a_gossip[0]["distortion"]) + 1
                if req.a_gossip else 0,
                topic=wire.topic or "general")
        return Conversation(
            turns=[Utterance(speaker=t.speaker, text=t.text)
                   for t in wire.turns[:req.max_turns]],
            gossip=gossip, sentiment=wire.sentiment,
            topic=wire.topic or "general")

    def reflect(self, req: ReflectRequest) -> Reflection:
        wire = self._ask("reflect", req.prompt, WireReflection)
        if wire is None:
            return self.fallback.reflect(req)
        return Reflection(insights=wire.insights[:4],
                          self_summary=wire.self_summary[:800])

    def react(self, req: ReactRequest) -> Reaction:
        wire = self._ask("react", req.prompt, WireReaction)
        if wire is None:
            return self.fallback.react(req)
        proposal = None
        if wire.interrupt and wire.affordance.strip():
            try:
                proposal = ActionProposal(affordance=wire.affordance,
                                          area=wire.area, reason=wire.reason)
            except ValueError:
                # an unknown affordance: drop the proposal, keep the thought
                self._note("react", f"bad affordance {wire.affordance!r}")
                return Reaction(interrupt=False, thought=wire.thought)
        return Reaction(interrupt=bool(proposal), proposal=proposal,
                        thought=wire.thought)

    def score_importance(self, req: ImportanceRequest) -> ImportanceScores:
        wire = self._ask("score_importance", req.prompt, WireScores)
        if wire is None:
            return self.fallback.score_importance(req)
        wanted = {mid for mid, _k, _t in req.items}
        scores = {
            int(i): max(1.0, min(10.0, float(s)))
            for i, s in zip(wire.ids, wire.scores)
            if int(i) in wanted
        }
        # anything the model skipped keeps its free heuristic score
        for mid, kind, text in req.items:
            scores.setdefault(mid, heuristic_importance(text, kind))
        return ImportanceScores(scores=scores)

    def stats(self) -> dict:
        return {
            "backend": self.name, "model": self.model, "calls": self.calls,
            "usage": dict(self.usage),
            "cache_hit_ratio": round(self.cache_hit_ratio, 3),
            "degradations": len(self.degradations),
            "recent_degradations": self.degradations[-5:],
        }


def _classify(exc: Exception) -> str:
    """Name the failure precisely, without importing the SDK at module level."""
    try:
        import anthropic
    except ImportError:                                    # pragma: no cover
        return type(exc).__name__
    if isinstance(exc, anthropic.NotFoundError):
        return "unknown model or endpoint"
    if isinstance(exc, anthropic.AuthenticationError):
        return "bad or missing credentials"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "credentials lack permission"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate limited"
    if isinstance(exc, anthropic.APITimeoutError):
        return "timed out"
    if isinstance(exc, anthropic.APIConnectionError):
        return "network unreachable"
    if isinstance(exc, anthropic.APIStatusError):
        code = getattr(exc, "status_code", 0)
        return f"server error {code}" if code >= 500 else f"api error {code}"
    return type(exc).__name__


def price_run(usage: dict, model: str = MODEL) -> float:
    """What a run actually cost, from reported usage rather than estimates."""
    from .budget import MODEL_PRICING

    fresh, cached, out = MODEL_PRICING.get(model, (0.0, 0.0, 0.0))
    return (
        (usage.get("input", 0) + usage.get("cache_write", 0) * 1.25) * fresh
        + usage.get("cache_read", 0) * cached
        + usage.get("output", 0) * out
    ) / 1_000_000


def sample_payload() -> str:
    """A pretty-printed strict schema, for eyeballing what the model is sent."""
    return json.dumps(strict_schema(WireConversation), indent=2)
