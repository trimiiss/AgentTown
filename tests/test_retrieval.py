"""Retrieval scores recency + importance + relevance.

Each component is checked in isolation, because a scorer where one term
silently dominates looks fine in aggregate and ranks badly in practice.
"""

from __future__ import annotations

import dataclasses

import pytest

from agenttown.memory.embed import HashedBowEmbedder
from agenttown.memory.importance import heuristic_importance, is_ambiguous
from agenttown.memory.retrieval import MemoryIndex
from agenttown.memory.store import MemoryStore

FIXTURE = [
    ("observation", "I walked down Carshia past the school", 0),
    ("observation", "I bought bread at the furra for 0.50 euro", 2),
    ("dialogue", "Arben told me Agim raised the price of bread to 0.95", 6),
    ("observation", "I prayed at the xhamia", 10),
    ("observation", "Vlora passed me on the street", 12),
    ("reflection", "Money is getting tighter in this town", 14),
]


def fresh_index(cfg, **weights):
    retrieval = dataclasses.replace(cfg.retrieval, **weights) if weights \
        else cfg.retrieval
    embedder = HashedBowEmbedder(cfg.memory.embed_dim)
    store = MemoryStore(":memory:", cfg.memory.embed_dim)
    index = MemoryIndex(store, embedder, retrieval, working_set=200)
    for kind, text, tick in FIXTURE:
        index.add("fatime", kind, text, tick)
    return index


def test_relevance_alone_finds_the_bread_memory(cfg):
    index = fresh_index(cfg, w_recency=0.0, w_importance=0.0, w_relevance=1.0)
    top = index.retrieve("fatime", "the price of bread", 20, k=1)
    assert "price of bread" in top[0].memory.text


def test_recency_alone_prefers_the_newest(cfg):
    index = fresh_index(cfg, w_recency=1.0, w_importance=0.0, w_relevance=0.0)
    top = index.retrieve("fatime", "anything at all", 20, k=1)
    assert top[0].memory.created_tick == max(t for _k, _x, t in FIXTURE)


def test_importance_alone_prefers_the_weightiest(cfg):
    index = fresh_index(cfg, w_recency=0.0, w_importance=1.0, w_relevance=0.0)
    top = index.retrieve("fatime", "anything at all", 20, k=1)
    best = max(FIXTURE, key=lambda f: heuristic_importance(f[1], f[0]))
    assert top[0].memory.text == best[1]


def test_components_disagree_so_the_blend_is_doing_work(cfg):
    picks = {
        name: fresh_index(cfg, **w).retrieve("fatime", "the price of bread", 20, k=1)[0]
        .memory.text
        for name, w in (
            ("recency", dict(w_recency=1.0, w_importance=0.0, w_relevance=0.0)),
            ("importance", dict(w_recency=0.0, w_importance=1.0, w_relevance=0.0)),
            ("relevance", dict(w_recency=0.0, w_importance=0.0, w_relevance=1.0)),
        )
    }
    assert len(set(picks.values())) > 1, f"all components agree: {picks}"


def test_breakdown_is_exposed_for_the_inspector(cfg):
    index = fresh_index(cfg)
    top = index.retrieve("fatime", "the price of bread", 20, k=3)
    for scored in top:
        b = scored.as_dict()["breakdown"]
        assert set(b) == {"recency", "importance", "relevance", "score"}
        assert all(0.0 <= b[k] <= 1.0 for k in ("recency", "importance"))


def test_retrieval_refreshes_recency(cfg):
    index = fresh_index(cfg)
    oldest = index.retrieve("fatime", "walked down Carshia", 20, k=1)[0].memory
    assert oldest.last_access == 20


def test_working_set_caps_ram_but_not_sqlite(cfg):
    embedder = HashedBowEmbedder(cfg.memory.embed_dim)
    store = MemoryStore(":memory:", cfg.memory.embed_dim)
    index = MemoryIndex(store, embedder, cfg.retrieval, working_set=40)
    for i in range(120):
        index.add("agim", "observation", f"I sold loaf number {i}", i)
    assert index.working_set_size("agim") <= 40
    assert store.count("agim") == 120
    assert index.evicted > 0


def test_empty_stream_retrieves_nothing(cfg):
    index = fresh_index(cfg)
    assert index.retrieve("nobody", "anything", 5) == []


@pytest.mark.parametrize("text,floor", [
    ("I walked down the street", 1.0),
    ("Agim raised the price of bread to 0.95 euro", 6.0),
    ("an election has been called for next week", 7.0),
    ("Fatime died in the night", 9.0),
])
def test_importance_bands_are_ordered(text, floor):
    assert heuristic_importance(text) >= floor


def test_only_the_middle_band_is_worth_an_llm_call():
    assert not is_ambiguous(heuristic_importance("I walked to the shop"))
    assert is_ambiguous(5.0)
    assert not is_ambiguous(9.5)


def test_embedding_is_deterministic_and_normalised(cfg):
    e = HashedBowEmbedder(cfg.memory.embed_dim)
    v1, v2 = e.encode("the price of bread"), e.encode("the price of bread")
    assert (v1 == v2).all()
    assert abs(float((v1 * v1).sum()) - 1.0) < 1e-5
    assert e.similarity("the price of bread", "bread costs more now") > \
        e.similarity("the price of bread", "he prayed at the mosque")
