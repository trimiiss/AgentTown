"""Text embeddings for memory retrieval.

Under the mock backend this is a signed hashing-trick projection of unigrams
and bigrams: a real, deterministic lexical retriever that costs nothing and
needs no model. It is good enough that retrieval quality is genuinely testable
before any tokens are bought. Swapping in a learned embedder later means
implementing Embedder.encode and nothing else.
"""

from __future__ import annotations

import re
import zlib
from typing import Protocol

import numpy as np

_TOKEN = re.compile(r"[\wÀ-ɏ]+", re.UNICODE)

STOPWORDS = frozenset("""
a an the and or but if then than that this these those of to in on at for with
from by as is are was were be been being has have had do does did will would
can could should may might must i me my you your he him his she her it its we
us our they them their there here what which who whom when where why how not no
nor so too very just about into over under again once only own same s t
""".split())


class Embedder(Protocol):
    dim: int

    def encode(self, text: str) -> np.ndarray: ...


class HashedBowEmbedder:
    """Signed random projection of unigrams + bigrams, L2-normalised."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    @staticmethod
    def tokens(text: str) -> list[str]:
        words = [w.lower() for w in _TOKEN.findall(text)]
        kept = [w for w in words if w not in STOPWORDS and len(w) > 1]
        bigrams = [f"{a}_{b}" for a, b in zip(kept, kept[1:])]
        return kept + bigrams

    def encode(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in self.tokens(text):
            h = zlib.crc32(tok.encode("utf-8"))
            v[h % self.dim] += 1.0 if (h >> 17) & 1 else -1.0
        norm = float(np.linalg.norm(v))
        return v / norm if norm > 0.0 else v

    def similarity(self, a: str, b: str) -> float:
        return float(self.encode(a) @ self.encode(b))
