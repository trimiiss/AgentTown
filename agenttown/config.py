"""Typed access to config/sim.toml.

Everything that makes a run reproducible is here, so a run is fully described
by (this file, town.json, agents.json, seed).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SimCfg:
    seed: int
    ticks_per_day: int
    minutes_per_tick: int
    real_ms_per_tick: int
    walk_speed: int
    start_hour: int
    plan_hour: int
    autostart: bool


@dataclass(frozen=True)
class NeedsCfg:
    hunger_per_tick: float
    fatigue_per_tick: float
    loneliness_per_tick: float
    act_threshold: float
    urgent_threshold: float


@dataclass(frozen=True)
class RetrievalCfg:
    w_recency: float
    w_importance: float
    w_relevance: float
    recency_half_life_ticks: int
    top_k: int


@dataclass(frozen=True)
class MemoryCfg:
    embed_dim: int
    working_set: int
    db: str
    reflection_threshold: float


@dataclass(frozen=True)
class EconomyCfg:
    starting_money: float
    prices: dict[str, float]
    wages: dict[str, float]
    daily_household_cost: float
    daily_vendor_cost: float
    weekly_support: float
    cost_of_goods: float
    wealth_spend_rate: float


@dataclass(frozen=True)
class ConversationCfg:
    cooldown_ticks: int
    min_social_need: float
    max_turns: int


@dataclass(frozen=True)
class CognitionCfg:
    backend: str
    model: str
    budget: dict[str, int]


@dataclass(frozen=True)
class RecorderCfg:
    enabled: bool
    dir: str


@dataclass(frozen=True)
class Config:
    root: Path
    sim: SimCfg
    needs: NeedsCfg
    retrieval: RetrievalCfg
    memory: MemoryCfg
    economy: EconomyCfg
    conversation: ConversationCfg
    cognition: CognitionCfg
    recorder: RecorderCfg
    town_path: Path
    agents_path: Path
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path = "config/sim.toml", root: str | Path | None = None) -> "Config":
        path = Path(path)
        root = Path(root) if root is not None else path.resolve().parent.parent
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        econ = raw["economy"]
        return cls(
            root=root,
            sim=SimCfg(**raw["sim"]),
            needs=NeedsCfg(**raw["needs"]),
            retrieval=RetrievalCfg(**raw["retrieval"]),
            memory=MemoryCfg(**raw["memory"]),
            economy=EconomyCfg(
                starting_money=econ["starting_money"],
                prices=dict(econ["prices"]),
                wages=dict(econ["wages"]),
                daily_household_cost=float(econ["daily_household_cost"]),
                daily_vendor_cost=float(econ["daily_vendor_cost"]),
                weekly_support=float(econ["weekly_support"]),
                cost_of_goods=float(econ["cost_of_goods"]),
                wealth_spend_rate=float(econ["wealth_spend_rate"]),
            ),
            conversation=ConversationCfg(**raw["conversation"]),
            cognition=CognitionCfg(
                backend=raw["cognition"]["backend"],
                model=raw["cognition"].get("model", "claude-haiku-5-5"),
                budget=dict(raw["cognition"]["budget"]),
            ),
            recorder=RecorderCfg(**raw["recorder"]),
            town_path=root / raw["world"]["town"],
            agents_path=root / raw["world"]["agents"],
            raw=raw,
        )

    # --- clock helpers -------------------------------------------------
    def day_of(self, tick: int) -> int:
        return tick // self.sim.ticks_per_day

    def minute_of_day(self, tick: int) -> int:
        start = self.sim.start_hour * 60
        return (start + (tick % self.sim.ticks_per_day) * self.sim.minutes_per_tick) % 1440

    def hour_of(self, tick: int) -> int:
        return self.minute_of_day(tick) // 60

    def clock(self, tick: int) -> str:
        m = self.minute_of_day(tick)
        return f"{m // 60:02d}:{m % 60:02d}"

    def db_path(self) -> Path:
        return self.root / self.memory.db

    def recorder_dir(self) -> Path:
        return self.root / self.recorder.dir
