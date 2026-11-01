"""Deterministic RNG streams.

Python's builtin hash() is salted per process, so it can never appear in a
reproducible simulation. Every random decision draws from a stream derived
from (seed, *parts) through blake2b, which means a decision depends only on
who is making it and when - never on agent iteration order.
"""

from __future__ import annotations

import hashlib
import random


def digest(seed: int, *parts: object) -> int:
    payload = repr((seed, *parts)).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def stream(seed: int, *parts: object) -> random.Random:
    """A fresh Random bound to this exact (seed, *parts) coordinate."""
    return random.Random(digest(seed, *parts))


def chance(seed: int, p: float, *parts: object) -> bool:
    """Deterministic coin flip - no Random object allocated."""
    return (digest(seed, *parts) % 1_000_000) < p * 1_000_000
