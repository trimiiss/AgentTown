"""Retrieval: recency + importance + relevance, Stanford-style.

Each component is min-max normalised across the candidate set before the
weighted sum, so no single component can dominate on scale alone - and so the
inspector can show a meaningful per-component breakdown of why a memory
surfaced.

The in-RAM working set is capped per agent; beyond the cap the least recently
accessed embeddings are dropped from memory but stay in SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import RetrievalCfg
from .embed import Embedder
from .importance import heuristic_importance
from .store import Memory, MemoryStore


@dataclass
class Scored:
    memory: Memory
    recency: float
    importance: float
    relevance: float
    score: float

    def as_dict(self) -> dict:
        d = self.memory.as_dict()
        d["breakdown"] = {
            "recency": round(self.recency, 3),
            "importance": round(self.importance, 3),
            "relevance": round(self.relevance, 3),
            "score": round(self.score, 3),
        }
        return d


def _minmax(v: np.ndarray) -> np.ndarray:
    if v.size == 0:
        return v
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        return np.ones_like(v) * 0.5
    return (v - lo) / (hi - lo)


class MemoryIndex:
    """Write-through cache over MemoryStore that owns retrieval."""

    def __init__(self, store: MemoryStore, embedder: Embedder,
                 cfg: RetrievalCfg, working_set: int = 1500) -> None:
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self.working_set = working_set
        self._mem: dict[str, list[Memory]] = {}
        self._emb: dict[str, np.ndarray] = {}
        self.retrievals = 0
        self.evicted = 0

    # --- writing -------------------------------------------------------
    def add(self, agent_id: str, kind: str, text: str, tick: int,
            importance: float | None = None, subject_ids: tuple[str, ...] = (),
            source: str | None = None) -> Memory:
        if importance is None:
            importance = heuristic_importance(text, kind)
        emb = self.embedder.encode(text)
        mem = self.store.add(agent_id, kind, text, tick, importance, emb,
                             subject_ids, source)
        rows = self._mem.setdefault(agent_id, [])
        rows.append(mem)
        stack = self._emb.get(agent_id)
        self._emb[agent_id] = (
            emb.reshape(1, -1) if stack is None
            else np.vstack([stack, emb.reshape(1, -1)])
        )
        if len(rows) > self.working_set:
            self._evict(agent_id)
        return mem

    def _evict(self, agent_id: str) -> None:
        """Drop the coldest third of the working set from RAM (not from SQLite)."""
        rows = self._mem[agent_id]
        keep_n = int(self.working_set * 0.67)
        order = sorted(range(len(rows)),
                       key=lambda i: (rows[i].last_access, rows[i].importance),
                       reverse=True)[:keep_n]
        order.sort()
        self.evicted += len(rows) - len(order)
        self._mem[agent_id] = [rows[i] for i in order]
        self._emb[agent_id] = self._emb[agent_id][order]

    def warm(self, agent_id: str) -> None:
        """Load an agent's memories from SQLite into the working set."""
        rows = list(reversed(self.store.for_agent(agent_id, self.working_set)))
        rows = [r for r in rows if r.embedding is not None]
        self._mem[agent_id] = rows
        self._emb[agent_id] = (
            np.vstack([r.embedding.reshape(1, -1) for r in rows])
            if rows else np.zeros((0, self.embedder.dim), dtype=np.float32)
        )

    # --- reading -------------------------------------------------------
    def retrieve(self, agent_id: str, query: str, tick: int,
                 k: int | None = None, kinds: tuple[str, ...] = ()) -> list[Scored]:
        rows = self._mem.get(agent_id) or []
        if not rows:
            return []
        k = k or self.cfg.top_k
        emb = self._emb[agent_id]

        idx = np.arange(len(rows))
        if kinds:
            mask = np.array([r.kind in kinds for r in rows], dtype=bool)
            idx = idx[mask]
            if idx.size == 0:
                return []

        q = self.embedder.encode(query)
        relevance = emb[idx] @ q

        half = max(1, self.cfg.recency_half_life_ticks)
        age = np.array([tick - rows[i].last_access for i in idx], dtype=np.float32)
        recency = np.power(0.5, np.maximum(age, 0.0) / half)
        importance = np.array([rows[i].importance for i in idx], dtype=np.float32) / 10.0

        score = (self.cfg.w_recency * _minmax(recency)
                 + self.cfg.w_importance * _minmax(importance)
                 + self.cfg.w_relevance * _minmax(relevance))

        top = idx[np.argsort(-score)[:k]]
        rank = {int(v): int(p) for p, v in enumerate(idx)}
        out = [
            Scored(rows[int(i)], float(recency[rank[int(i)]]),
                   float(importance[rank[int(i)]]), float(relevance[rank[int(i)]]),
                   float(score[rank[int(i)]]))
            for i in top
        ]
        hit_ids = [s.memory.id for s in out]
        self.store.touch(hit_ids, tick)
        for s in out:
            s.memory.last_access = tick
        self.retrievals += 1
        return out

    def recent(self, agent_id: str, n: int, kinds: tuple[str, ...] = ()) -> list[Memory]:
        rows = self._mem.get(agent_id) or []
        if kinds:
            rows = [r for r in rows if r.kind in kinds]
        return list(reversed(rows[-n:]))

    def working_set_size(self, agent_id: str) -> int:
        return len(self._mem.get(agent_id) or [])

    def stats(self) -> dict:
        return {
            "retrievals": self.retrievals,
            "evicted": self.evicted,
            "in_ram": sum(len(v) for v in self._mem.values()),
            "on_disk": self.store.count(),
        }
