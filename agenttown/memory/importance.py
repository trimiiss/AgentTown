"""Heuristic importance scoring, 1..10.

This is the default scorer: it runs on every new memory with no LLM call at
all. The score_importance LLM call type exists only to re-score the ambiguous
middle band in batches, so 90%+ of memories never cost anything.
"""

from __future__ import annotations

import re

#: weight -> words. The highest matching band wins.
BANDS: list[tuple[float, tuple[str, ...]]] = [
    (9.0, ("died", "death", "funeral", "fire", "arrested", "collapsed", "stolen",
           "robbed", "divorce", "hospital")),
    (7.5, ("election", "vote", "voting", "candidate", "pregnant", "engaged",
           "married", "wedding", "fired", "sacked", "accident", "ill", "sick",
           "fever", "closed down", "protest")),
    (6.0, ("raised the price", "raised prices", "price", "prices", "expensive",
           "cheaper", "argument", "argued", "shouted", "quarrel", "rumour",
           "rumor", "gossip", "complained", "refused", "owes", "debt", "loan",
           "remittance", "power cut", "electricity")),
    (4.5, ("told", "said", "promised", "agreed", "invited", "asked about",
           "offered", "warned", "decided")),
    (3.0, ("bought", "sold", "paid", "worked", "prayed", "taught", "studied",
           "met", "talked", "saw")),
    (1.5, ("walked", "arrived", "left", "entered", "sat", "stood", "woke",
           "slept", "passed")),
]

KIND_FLOOR = {
    "reflection": 6.5,   # insights are by construction more important than events
    "plan": 3.0,
    "dialogue": 3.5,
    "observation": 1.0,
}

_WORD = re.compile(r"[\wÀ-ɏ]+", re.UNICODE)


def heuristic_importance(text: str, kind: str = "observation") -> float:
    low = text.lower()
    score = 2.0
    for weight, words in BANDS:
        if any(w in low for w in words):
            score = weight
            break
    # A memory naming money tends to matter more than one that does not.
    if re.search(r"\d+[.,]\d{2}|\beuro?\b|€", low):
        score += 0.5
    score = max(score, KIND_FLOOR.get(kind, 1.0))
    return round(min(10.0, max(1.0, score)), 2)


def is_ambiguous(score: float) -> bool:
    """Scores in the middle band are the only ones worth spending a call on."""
    return 4.0 <= score <= 7.0
