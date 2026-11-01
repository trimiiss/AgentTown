"""Byte-deterministic tick log.

Seed plus this log equals an exact replay, which is what makes emergence
debuggable after the fact: you can ask why an agent stopped going to the
bakery and actually find out.

Determinism is fragile, so the writer is strict: sorted keys, fixed float
rounding, ASCII escaping, no timestamps, no insertion-ordered dicts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FLOAT_PLACES = 4


def canonical(value):
    """Recursively round floats and sort keys so output cannot wobble."""
    if isinstance(value, float):
        return round(value, FLOAT_PLACES)
    if isinstance(value, dict):
        return {k: canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, set):
        return [canonical(v) for v in sorted(value, key=str)]
    return value


def encode(payload: dict) -> str:
    return json.dumps(canonical(payload), sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


class Recorder:
    def __init__(self, path: str | Path | None, enabled: bool = True) -> None:
        self.enabled = enabled and path is not None
        self.path = Path(path) if path is not None else None
        self.lines = 0
        self._hash = hashlib.blake2b(digest_size=16)
        self._fh = None
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("w", encoding="utf-8", newline="\n")

    def write(self, payload: dict) -> str:
        line = encode(payload)
        self._hash.update(line.encode("utf-8"))
        self._hash.update(b"\n")
        self.lines += 1
        if self._fh is not None:
            self._fh.write(line + "\n")
        return line

    @property
    def digest(self) -> str:
        """Running hash of the whole run - the replay test compares these."""
        return self._hash.hexdigest()

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
