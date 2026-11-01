"""The single most valuable test: a seed must reproduce a run exactly.

Without this you cannot answer "why did that emerge?", because you cannot get
back to the run that produced it.
"""

from __future__ import annotations

from .conftest import build


def _run(cfg, seed=None, ticks=180):
    sim = build(cfg, seed=seed)
    sim.run(ticks // 2)
    sim.inject("price_change", {"item": "bread", "factor": 1.8})
    sim.inject("election_called", {"when": "next Sunday"})
    sim.run(ticks - ticks // 2)
    out = (sim.recorder.digest, sim.snapshot())
    sim.close()
    return out


def test_same_seed_is_byte_identical(cfg):
    a_digest, a_snap = _run(cfg)
    b_digest, b_snap = _run(cfg)
    assert a_digest == b_digest
    for key in ("decisions_by_tier", "economy", "gossip", "policy_cache",
                "memory", "validator"):
        assert a_snap[key] == b_snap[key], f"{key} is not reproducible"


def test_different_seed_diverges(cfg):
    a_digest, _ = _run(cfg)
    b_digest, _ = _run(cfg, seed=cfg.sim.seed + 1)
    assert a_digest != b_digest


def test_agent_order_is_total(sim):
    assert sim.order == sorted(sim.order)
    assert len(sim.order) == len(set(sim.order))


def test_recorder_canonicalises_floats_and_key_order():
    from agenttown.sim.recorder import encode

    left = encode({"b": 1 / 3, "a": [2 / 3, {"d": 1, "c": 2}]})
    right = encode({"a": [2 / 3, {"c": 2, "d": 1}], "b": 1 / 3})
    assert left == right
    assert "0.3333" in left and "0.33333" not in left
