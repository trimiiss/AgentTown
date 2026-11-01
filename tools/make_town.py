"""Generate config/town.json: a 60x40 Kosovar town.

Buildings are stamped as walled rectangles with a walkable interior and one
door tile, so agents can actually walk inside. Run from the repo root:

    uv run python tools/make_town.py

The script asserts row widths, door walkability and full connectivity before
writing, so a broken map fails here rather than at simulation time.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

W, H = 60, 40
GROUND, WALL, GRASS = ".", "#", ","

# id, name, kind, x0, y0, x1, y1, door (x, y)
BUILDINGS = [
    ("home_berisha",  "Shtëpia e Berishajve", "home",         8,  2, 14,  7, (11,  7)),
    ("home_krasniqi", "Shtëpia e Krasniqit",  "home",        17,  2, 23,  7, (20,  7)),
    ("home_gashi",    "Shtëpia e Gashit",     "home",        34,  2, 40,  7, (37,  7)),
    ("home_morina",   "Shtëpia e Morinës",    "home",        43,  2, 49,  7, (46,  7)),
    ("xhamia",        "Xhamia e Çarshisë",    "mosque",       8, 11, 16, 17, (12, 17)),
    ("shkolla",       "Shkolla Naim Frashëri","school",      19, 11, 29, 17, (24, 17)),
    ("komuna",        "Komuna",               "municipality",34, 11, 44, 17, (39, 17)),
    ("furra",         "Furra e Çarshisë",     "bakery",       8, 21, 14, 27, (11, 21)),
    ("kafiteria",     "Kafiteria Çarshia",    "cafe",        17, 21, 23, 27, (20, 21)),
    ("ambulanca",     "Ambulanca",            "clinic",      25, 21, 29, 27, (27, 21)),
    ("dyqani",        "Dyqani i Shpendit",      "shop",        47, 21, 53, 27, (50, 21)),
    ("kisha",         "Kisha e Shën Nikollës","church",       8, 31, 16, 37, (12, 31)),
    ("home_hoxha",    "Shtëpia e Hoxhës",     "home",        19, 31, 25, 37, (22, 31)),
    ("home_bytyqi",   "Shtëpia e Bytyqit",    "home",        34, 31, 40, 37, (37, 31)),
    ("home_shala",    "Shtëpia e Shalës",     "home",        43, 31, 49, 37, (46, 31)),
    # A second wave of housing, so the town can hold 20-50 residents.
    ("home_zariqi",   "Shtëpia e Zariqit",    "home",         1,  2,  7,  7, ( 4,  7)),
    ("home_dervishi", "Shtëpia e Dervishit",  "home",        25,  2, 31,  7, (28,  7)),
    ("home_rexhepi",  "Shtëpia e Rexhepit",   "home",        51,  2, 57,  7, (54,  7)),
    ("home_kelmendi", "Shtëpia e Kelmendit",  "home",         1, 31,  7, 37, ( 4, 31)),
    ("home_ademi",    "Shtëpia e Ademit",     "home",        27, 31, 33, 37, (30, 31)),
    ("home_sokoli",   "Shtëpia e Sokolit",    "home",        51, 31, 57, 37, (54, 31)),
]

# Open areas: walkable grass, no walls. id, name, kind, x0, y0, x1, y1
OPEN_AREAS = [
    ("pazari", "Pazari",          "market", 34, 21, 44, 27),
    ("parku",  "Parku i Qytetit", "park",   47, 11, 53, 17),
]

# The high street. Doors on y=17 and y=21 open onto it.
STREET = ("carshia", "Çarshia", "street", 1, 18, 58, 20)

# id, name, x, y, area, affordances, props
OBJECTS = [
    ("furra_oven",    "furrë buke",      10, 24, "furra",     ["work"], {}),
    ("furra_counter", "banaku i furrës", 12, 23, "furra",     ["buy_bread"], {"item": "bread"}),
    ("kafe_counter",  "banaku i kafes",  19, 23, "kafiteria", ["buy_coffee", "work"], {"item": "coffee"}),
    ("kafe_table_a",  "tavolina e kafes",21, 25, "kafiteria", ["sit", "socialize"], {}),
    ("kafe_table_b",  "tavolina e dritares",22, 24,"kafiteria",["sit", "socialize"], {}),
    ("dyqan_counter", "banaku i dyqanit",49, 23, "dyqani",    ["buy_cigarettes", "work"], {"item": "cigarettes"}),
    ("amb_desk",      "tavolina e motrës",27, 23, "ambulanca",["work"], {}),
    ("amb_bed",       "shtrati i pacientit",27,25, "ambulanca",["buy_medicine", "treat"], {"item": "medicine"}),
    ("shkolla_desk",  "katedra",         24, 13, "shkolla",   ["work"], {}),
    ("shkolla_bench", "banka e nxënësve",22, 15, "shkolla",   ["study", "sit"], {}),
    ("komuna_desk",   "zyra e komunës",  39, 13, "komuna",    ["work"], {}),
    ("komuna_ballot", "kutia e votimit", 41, 15, "komuna",    ["vote"], {}),
    ("xhamia_mat",    "sexhadeja",       12, 14, "xhamia",    ["pray"], {}),
    ("xhamia_minber", "minberi",         10, 13, "xhamia",    ["work", "pray"], {}),
    ("kisha_altar",   "altari",          12, 34, "kisha",     ["pray"], {}),
    ("kisha_pew",     "stolat",          10, 35, "kisha",     ["pray", "sit"], {}),
    ("pazar_stall_a", "tezga e perimeve",36, 23, "pazari",    ["shop", "socialize"], {}),
    ("pazar_stall_b", "tezga e mishit",  39, 25, "pazari",    ["shop", "socialize"], {}),
    ("pazar_stall_c", "tezga e rrobave", 42, 23, "pazari",    ["shop", "socialize"], {}),
    ("parku_bench_a", "stoli i parkut",  49, 14, "parku",     ["sit", "socialize"], {}),
    ("parku_bench_b", "stoli nën lis",   51, 16, "parku",     ["sit", "socialize"], {}),
]


def home_objects() -> list[tuple]:
    """Every home gets a bed and a table, so sleep and eat resolve to objects."""
    out = []
    for aid, name, kind, x0, y0, x1, y1, _door in BUILDINGS:
        if kind != "home":
            continue
        short = aid.replace("home_", "")
        out.append((f"{short}_bed", "shtrati", x0 + 2, y0 + 2, aid, ["sleep"], {}))
        out.append((f"{short}_table", "tryeza", x0 + 4, y0 + 3, aid,
                    ["eat", "sit"], {}))
    return out


def build() -> dict:
    g = [[GROUND] * W for _ in range(H)]

    for x in range(W):
        g[0][x] = g[H - 1][x] = WALL
    for y in range(H):
        g[y][0] = g[y][W - 1] = WALL

    for _id, _name, _kind, x0, y0, x1, y1 in OPEN_AREAS:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                g[y][x] = GRASS

    areas = []
    for aid, name, kind, x0, y0, x1, y1, door in BUILDINGS:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                on_edge = x in (x0, x1) or y in (y0, y1)
                g[y][x] = WALL if on_edge else GROUND
        dx, dy = door
        g[dy][dx] = GROUND
        areas.append({
            "id": aid, "name": name, "kind": kind,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "entrance": [dx, dy],
        })

    for aid, name, kind, x0, y0, x1, y1 in OPEN_AREAS:
        areas.append({
            "id": aid, "name": name, "kind": kind,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "entrance": [(x0 + x1) // 2, (y0 + y1) // 2],
        })

    aid, name, kind, x0, y0, x1, y1 = STREET
    areas.append({
        "id": aid, "name": name, "kind": kind,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "entrance": [(x0 + x1) // 2, (y0 + y1) // 2],
    })

    terrain = ["".join(row) for row in g]
    verify(terrain, areas)
    return {
        "width": W, "height": H,
        "legend": {GROUND: "ground", WALL: "wall", GRASS: "grass"},
        "terrain": terrain,
        "areas": areas,
        "objects": [
            {"id": i, "name": n, "x": x, "y": y, "area": a,
             "affordances": aff, "props": p}
            for i, n, x, y, a, aff, p in OBJECTS
        ],
    }


def verify(terrain: list[str], areas: list[dict]) -> None:
    assert len(terrain) == H, f"expected {H} rows, got {len(terrain)}"
    for y, row in enumerate(terrain):
        assert len(row) == W, f"row {y} is {len(row)} wide, expected {W}"

    walkable = lambda x, y: 0 <= x < W and 0 <= y < H and terrain[y][x] != WALL

    for a in areas:
        ex, ey = a["entrance"]
        assert walkable(ex, ey), f"{a['id']}: entrance {ex},{ey} is not walkable"

    # Every area entrance must be reachable from the middle of the high street.
    start = tuple(next(a for a in areas if a["id"] == "carshia")["entrance"])
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if walkable(nx, ny) and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    for a in areas:
        assert tuple(a["entrance"]) in seen, f"{a['id']} is unreachable from Çarshia"

    for o in OBJECTS:
        oid, _n, x, y, area_id, _aff, _p = o
        assert walkable(x, y), f"object {oid} sits on a wall at {x},{y}"
        a = next(a for a in areas if a["id"] == area_id)
        assert a["x0"] <= x <= a["x1"] and a["y0"] <= y <= a["y1"], \
            f"object {oid} at {x},{y} is outside area {area_id}"
        assert tuple((x, y)) in seen, f"object {oid} is unreachable"


OBJECTS.extend(home_objects())


if __name__ == "__main__":
    town = build()
    out = Path("config/town.json")
    out.write_text(json.dumps(town, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} - {W}x{H}, {len(town['areas'])} areas, {len(town['objects'])} objects")
    print("\n".join(town["terrain"]))
