"""4-directional A* over the tile grid, with a path cache.

Terrain is static for a whole run, so each (start, goal) path is computed once
and reused. That is what keeps Tier 0 movement for 50 agents essentially free.
"""

from __future__ import annotations

import heapq

from .grid import Grid

Point = tuple[int, int]
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Pathfinder:
    def __init__(self, grid: Grid, cache_limit: int = 20_000) -> None:
        self.grid = grid
        self._cache: dict[tuple[Point, Point], list[Point]] = {}
        self._cache_limit = cache_limit
        self.computed = 0
        self.cache_hits = 0

    def path(self, start: Point, goal: Point) -> list[Point]:
        """Tiles to walk, excluding start, including goal. Empty if unreachable."""
        if start == goal:
            return []
        key = (start, goal)
        hit = self._cache.get(key)
        if hit is not None:
            self.cache_hits += 1
            return list(hit)
        result = self._astar(start, goal)
        if len(self._cache) >= self._cache_limit:
            self._cache.clear()
        self._cache[key] = result
        self.computed += 1
        return list(result)

    def _astar(self, start: Point, goal: Point) -> list[Point]:
        g = self.grid
        if not g.is_walkable(*goal) or not g.is_walkable(*start):
            return []

        def h(p: Point) -> int:
            return abs(p[0] - goal[0]) + abs(p[1] - goal[1])

        open_heap: list[tuple[int, int, Point]] = [(h(start), 0, start)]
        came: dict[Point, Point] = {}
        best: dict[Point, int] = {start: 0}
        while open_heap:
            _f, cost, cur = heapq.heappop(open_heap)
            if cur == goal:
                out: list[Point] = []
                while cur != start:
                    out.append(cur)
                    cur = came[cur]
                out.reverse()
                return out
            if cost > best.get(cur, 1 << 30):
                continue
            cx, cy = cur
            for dx, dy in _NEIGHBOURS:
                nxt = (cx + dx, cy + dy)
                if not g.is_walkable(*nxt):
                    continue
                ncost = cost + 1
                if ncost < best.get(nxt, 1 << 30):
                    best[nxt] = ncost
                    came[nxt] = cur
                    heapq.heappush(open_heap, (ncost + h(nxt), ncost, nxt))
        return []

    def reachable(self, start: Point, goal: Point) -> bool:
        return start == goal or bool(self.path(start, goal))

    def stats(self) -> dict[str, int]:
        return {"computed": self.computed, "cache_hits": self.cache_hits,
                "cached_paths": len(self._cache)}
