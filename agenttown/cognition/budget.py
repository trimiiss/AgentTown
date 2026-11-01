"""Per-sim-day LLM call ceilings, and the cost counter.

When a ceiling is reached the call does not fail - it degrades to the mock
backend, which is the same code path the simulation was built on. That is why
the mock is permanent infrastructure rather than scaffolding.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .backend import CALL_TYPES

#: USD per million tokens: (fresh input, cached input, output)
MODEL_PRICING: dict[str, tuple[float, float, float]] = {
    "mock": (0.0, 0.0, 0.0),
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 0.20, 10.00),
    "local": (0.0, 0.0, 0.0),
}


@dataclass
class Spend:
    calls: int = 0
    fresh_in: int = 0
    cached_in: int = 0
    out: int = 0
    usd: float = 0.0


@dataclass
class Budget:
    limits: dict[str, int]
    ticks_per_day: int
    model: str = "mock"
    batch_discount: float = 0.5

    _day: int = -1
    used: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    degraded: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    spend: dict[str, Spend] = field(default_factory=lambda: defaultdict(Spend))
    total: Spend = field(default_factory=Spend)

    def _roll(self, tick: int) -> None:
        day = tick // self.ticks_per_day
        if day != self._day:
            self._day = day
            self.used = defaultdict(int)

    def allow(self, call_type: str, tick: int) -> bool:
        """True if this call may hit the model; False means use the fallback."""
        self._roll(tick)
        limit = self.limits.get(call_type, 0)
        if self.used[call_type] >= limit:
            self.degraded[call_type] += 1
            return False
        self.used[call_type] += 1
        return True

    def record(self, call_type: str, fresh_in: int, cached_in: int, out: int,
               model: str | None = None, batched: bool = False) -> float:
        p_fresh, p_cached, p_out = MODEL_PRICING.get(model or self.model, (0.0, 0.0, 0.0))
        usd = (fresh_in * p_fresh + cached_in * p_cached + out * p_out) / 1_000_000
        if batched:
            usd *= self.batch_discount
        for bucket in (self.spend[call_type], self.total):
            bucket.calls += 1
            bucket.fresh_in += fresh_in
            bucket.cached_in += cached_in
            bucket.out += out
            bucket.usd += usd
        return usd

    def stats(self) -> dict:
        return {
            "model": self.model,
            "day": self._day,
            "limits": dict(self.limits),
            "used_today": {k: self.used.get(k, 0) for k in CALL_TYPES},
            "degraded": {k: self.degraded.get(k, 0) for k in CALL_TYPES},
            "calls": {k: self.spend[k].calls for k in CALL_TYPES},
            "total_calls": self.total.calls,
            "total_usd": round(self.total.usd, 6),
            "tokens": {
                "fresh_in": self.total.fresh_in,
                "cached_in": self.total.cached_in,
                "out": self.total.out,
            },
            "usd_per_sim_day": round(
                self.total.usd / max(1, self._day + 1), 6
            ),
        }
