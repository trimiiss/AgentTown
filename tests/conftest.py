from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agenttown.config import Config
from agenttown.sim.loop import Simulation

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config.load(ROOT / "config" / "sim.toml", root=ROOT)


def build(cfg: Config, *, seed: int | None = None, **sim_overrides) -> Simulation:
    """A throwaway simulation: in-memory DB, no run log on disk."""
    if seed is not None:
        sim_overrides["seed"] = seed
    if sim_overrides:
        cfg = dataclasses.replace(
            cfg, sim=dataclasses.replace(cfg.sim, **sim_overrides))
    return Simulation(cfg, record=False, in_memory_db=True)


@pytest.fixture
def sim(cfg: Config):
    s = build(cfg)
    yield s
    s.close()


@pytest.fixture(scope="session")
def day(cfg: Config) -> int:
    return cfg.sim.ticks_per_day
