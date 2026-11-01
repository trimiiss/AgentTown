"""The memory stream, in SQLite.

One row per remembered thing. This is the only durable record of an agent's
inner life; structured world state (money, position, relationships) lives on
the agent and is never inferred from here.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id      TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    created_tick  INTEGER NOT NULL,
    importance    REAL    NOT NULL,
    last_access   INTEGER NOT NULL,
    subject_ids   TEXT    NOT NULL DEFAULT '[]',
    source        TEXT,
    embedding     BLOB
);
CREATE INDEX IF NOT EXISTS idx_mem_agent      ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_mem_agent_kind ON memories(agent_id, kind);
CREATE INDEX IF NOT EXISTS idx_mem_tick       ON memories(created_tick);
"""


@dataclass
class Memory:
    id: int
    agent_id: str
    kind: str
    text: str
    created_tick: int
    importance: float
    last_access: int
    subject_ids: tuple[str, ...] = ()
    source: str | None = None
    embedding: np.ndarray | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "text": self.text,
            "created_tick": self.created_tick,
            "importance": round(self.importance, 2),
            "last_access": self.last_access,
            "subjects": list(self.subject_ids), "source": self.source,
        }


class MemoryStore:
    def __init__(self, path: str | Path, dim: int, fresh: bool = False) -> None:
        self.dim = dim
        self.path = str(path)
        if self.path != ":memory:":
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if fresh:
                for suffix in ("", "-wal", "-shm"):
                    Path(self.path + suffix).unlink(missing_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- writes --------------------------------------------------------
    def add(self, agent_id: str, kind: str, text: str, tick: int,
            importance: float, embedding: np.ndarray | None = None,
            subject_ids: tuple[str, ...] = (), source: str | None = None) -> Memory:
        blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
        cur = self.db.execute(
            "INSERT INTO memories (agent_id, kind, text, created_tick, importance,"
            " last_access, subject_ids, source, embedding)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (agent_id, kind, text, tick, float(importance), tick,
             json.dumps(list(subject_ids)), source, blob),
        )
        return Memory(int(cur.lastrowid), agent_id, kind, text, tick,
                      float(importance), tick, tuple(subject_ids), source, embedding)

    def touch(self, ids: list[int], tick: int) -> None:
        if ids:
            self.db.executemany(
                "UPDATE memories SET last_access=? WHERE id=?",
                [(tick, i) for i in ids],
            )

    def set_importance(self, scores: dict[int, float]) -> None:
        if scores:
            self.db.executemany(
                "UPDATE memories SET importance=? WHERE id=?",
                [(float(v), k) for k, v in scores.items()],
            )

    def commit(self) -> None:
        self.db.commit()

    # --- reads ---------------------------------------------------------
    def _row(self, r: sqlite3.Row) -> Memory:
        emb = (np.frombuffer(r["embedding"], dtype=np.float32)
               if r["embedding"] is not None else None)
        return Memory(r["id"], r["agent_id"], r["kind"], r["text"],
                      r["created_tick"], r["importance"], r["last_access"],
                      tuple(json.loads(r["subject_ids"])), r["source"], emb)

    def for_agent(self, agent_id: str, limit: int | None = None) -> list[Memory]:
        q = ("SELECT * FROM memories WHERE agent_id=? "
             "ORDER BY created_tick DESC, id DESC")
        if limit:
            q += f" LIMIT {int(limit)}"
        return [self._row(r) for r in self.db.execute(q, (agent_id,))]

    def recent(self, agent_id: str, n: int, kinds: tuple[str, ...] = ()) -> list[Memory]:
        q = "SELECT * FROM memories WHERE agent_id=?"
        args: list = [agent_id]
        if kinds:
            q += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        q += " ORDER BY created_tick DESC, id DESC LIMIT ?"
        args.append(int(n))
        return [self._row(r) for r in self.db.execute(q, args)]

    def count(self, agent_id: str | None = None) -> int:
        if agent_id:
            row = self.db.execute(
                "SELECT COUNT(*) c FROM memories WHERE agent_id=?", (agent_id,)
            ).fetchone()
        else:
            row = self.db.execute("SELECT COUNT(*) c FROM memories").fetchone()
        return int(row["c"])

    def counts_by_agent(self) -> dict[str, int]:
        return {r["agent_id"]: r["c"] for r in self.db.execute(
            "SELECT agent_id, COUNT(*) c FROM memories GROUP BY agent_id")}

    def close(self) -> None:
        self.db.commit()
        self.db.close()
