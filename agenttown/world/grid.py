"""The tile world: terrain, semantic areas and placed objects."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

WALL = "#"


@dataclass(frozen=True)
class Area:
    id: str
    name: str
    kind: str
    x0: int
    y0: int
    x1: int
    y1: int
    entrance: tuple[int, int]

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    @property
    def center(self) -> tuple[int, int]:
        return (self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2


@dataclass(frozen=True)
class WorldObject:
    id: str
    name: str
    x: int
    y: int
    area: str
    affordances: tuple[str, ...]
    props: dict = field(default_factory=dict)

    @property
    def pos(self) -> tuple[int, int]:
        return self.x, self.y


class Grid:
    """Static terrain. Nothing here mutates during a run."""

    def __init__(self, width: int, height: int, terrain: list[str],
                 areas: list[Area], objects: list[WorldObject]) -> None:
        self.width = width
        self.height = height
        self.terrain = terrain
        self.areas: dict[str, Area] = {a.id: a for a in areas}
        self.objects: dict[str, WorldObject] = {o.id: o for o in objects}

        self.walkable = np.array(
            [[c != WALL for c in row] for row in terrain], dtype=bool
        )

        # Area lookup per tile. Buildings and open areas fill first so that a
        # street area can never shadow the room an agent is standing in.
        self._area_ids: list[str] = [a.id for a in areas]
        self._area_at = np.full((height, width), -1, dtype=np.int16)
        ordered = sorted(range(len(areas)), key=lambda i: areas[i].kind == "street")
        for i in ordered:
            a = areas[i]
            for y in range(a.y0, a.y1 + 1):
                for x in range(a.x0, a.x1 + 1):
                    if self._area_at[y, x] == -1:
                        self._area_at[y, x] = i

        self._by_affordance: dict[str, list[WorldObject]] = {}
        self._objects_by_area: dict[str, list[WorldObject]] = {}
        for o in self.objects.values():
            for aff in o.affordances:
                self._by_affordance.setdefault(aff, []).append(o)
            self._objects_by_area.setdefault(o.area, []).append(o)

        self._interior_cache: dict[str, list[tuple[int, int]]] = {}

    @classmethod
    def load(cls, path: str | Path) -> "Grid":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        areas = [
            Area(a["id"], a["name"], a["kind"], a["x0"], a["y0"], a["x1"], a["y1"],
                 (a["entrance"][0], a["entrance"][1]))
            for a in data["areas"]
        ]
        objects = [
            WorldObject(o["id"], o["name"], o["x"], o["y"], o["area"],
                        tuple(o["affordances"]), dict(o.get("props", {})))
            for o in data["objects"]
        ]
        return cls(data["width"], data["height"], data["terrain"], areas, objects)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and bool(self.walkable[y, x])

    def area_of(self, x: int, y: int) -> Area | None:
        if not self.in_bounds(x, y):
            return None
        i = int(self._area_at[y, x])
        return self.areas[self._area_ids[i]] if i >= 0 else None

    def area_name(self, x: int, y: int) -> str:
        a = self.area_of(x, y)
        return a.name if a else "the street"

    def objects_in(self, area_id: str) -> list[WorldObject]:
        return list(self._objects_by_area.get(area_id, ()))

    def objects_with(self, affordance: str) -> list[WorldObject]:
        return list(self._by_affordance.get(affordance, ()))

    def object_in_area_with(self, area_id: str, affordance: str) -> WorldObject | None:
        for o in self._objects_by_area.get(area_id, ()):
            if affordance in o.affordances:
                return o
        return None

    def nearest_object_with(self, x: int, y: int, affordance: str) -> WorldObject | None:
        best, best_d = None, 1 << 30
        for o in self._by_affordance.get(affordance, ()):
            d = abs(o.x - x) + abs(o.y - y)
            if d < best_d:
                best, best_d = o, d
        return best

    def interior_tiles(self, area_id: str) -> list[tuple[int, int]]:
        """Walkable tiles inside an area - where an agent may legitimately stand."""
        if area_id not in self._interior_cache:
            a = self.areas[area_id]
            self._interior_cache[area_id] = [
                (x, y)
                for y in range(a.y0, a.y1 + 1)
                for x in range(a.x0, a.x1 + 1)
                if self.is_walkable(x, y)
            ]
        return self._interior_cache[area_id]

    def random_tile_in(self, area_id: str, rng: random.Random) -> tuple[int, int]:
        tiles = self.interior_tiles(area_id)
        if not tiles:
            return self.areas[area_id].entrance
        return rng.choice(tiles)
