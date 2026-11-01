"""Build config/cast.json: the authored characters plus templated residents.

Twelve people are hand-written in config/agents.json, because a town needs a
few residents with real interiority for anything interesting to happen. The
rest are generated here from name pools and household templates - enough to
fill the map, give the authored cast somebody to talk to, and put the cost
model under realistic load.

config/agents.json stays the hand-editable source of truth; this script never
writes to it. Run from the repo root:

    uv run python tools/make_cast.py --total 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agenttown.sim.rng import stream

SEED = 20260101

MALE = ["Fatos", "Bekim", "Driton", "Naim", "Valon", "Astrit", "Gezim", "Lulzim",
        "Burim", "Xhavit", "Kujtim", "Mentor", "Petrit", "Sokol", "Granit"]
FEMALE = ["Shpresa", "Mirlinda", "Valbona", "Arta", "Donika", "Lumturie", "Edona",
          "Gentiana", "Albana", "Majlinda", "Shqipe", "Dafina", "Hajrije"]
SURNAMES = ["Zariqi", "Dervishi", "Rexhepi", "Kelmendi", "Ademi", "Sokoli",
            "Berisha", "Krasniqi", "Gashi", "Morina", "Hoxha", "Bytyqi", "Shala"]

#: occupation -> (workplace area or None, work hours or None, weight)
TRADES: list[tuple[str, str | None, tuple[int, int] | None, int]] = [
    ("mechanic", "pazari", (8, 18), 2),
    ("seamstress", "pazari", (9, 17), 2),
    ("farmer", "pazari", (6, 15), 3),
    ("driver", "carshia", (7, 19), 2),
    ("labourer", "pazari", (7, 17), 3),
    ("barber", "pazari", (9, 19), 1),
    ("butcher", "pazari", (7, 16), 1),
    ("cleaner", "shkolla", (6, 12), 2),
    ("waiter", "kafiteria", (9, 21), 1),
    ("housewife", None, None, 4),
    ("pensioner", None, None, 3),
    ("unemployed", None, None, 3),
    ("student", "shkolla", (8, 14), 3),
]

TRAITS = [
    "quiet in company", "quick to take offence", "endlessly patient",
    "never stops working", "superstitious", "generous with what little there is",
    "sharp about money", "sentimental about the old days", "suspicious of officials",
    "cheerful on no evidence", "stubborn", "kind to children",
    "takes everything personally", "unbothered by anything", "proud",
    "complains constantly and means none of it", "keeps to a routine",
    "forgets names and not faces",
]
TICS = [
    "starts sentences twice", "ends every point with a shrug",
    "says 'inshallah' about the weather", "repeats your name back to you",
    "answers before you finish", "trails off mid-sentence",
    "laughs at the end of bad news", "speaks very quietly",
]
BACKSTORY = [
    "{first} has lived on this street since before the school was rebuilt, and intends to die on it.",
    "{first} came back from abroad with savings that lasted two winters.",
    "{first} has worked since the age of fourteen and does not expect to stop.",
    "{first} raised four children in this house and now rattles around it.",
    "{first} is the one the neighbours call when something needs carrying.",
    "{first} has a brother in Germany who sends money and never visits.",
    "{first} has never been further than Prishtina and sees no reason to go.",
    "{first} took over the family plot and has been losing money on it politely ever since.",
    "{first} keeps saying this is the last year in this town.",
]
TAGS = ["neighbour", "cousin", "old schoolmate", "drinks coffee with him",
        "owes him money", "does not speak to him much", "distant relative"]


def generate(authored: list[dict], total: int, town: dict) -> list[dict]:
    rng = stream(SEED, "cast", total)
    taken = {a["id"] for a in authored}
    homes = [a["id"] for a in town["areas"] if a["kind"] == "home"]
    occupied: dict[str, int] = {}
    for a in authored:
        occupied[a["home"]] = occupied.get(a["home"], 0) + 1

    trades: list[tuple[str, str | None, tuple[int, int] | None]] = []
    for name, area, hours, weight in TRADES:
        trades.extend([(name, area, hours)] * weight)

    out: list[dict] = []
    while len(authored) + len(out) < total:
        female = rng.random() < 0.5
        first = rng.choice(FEMALE if female else MALE)
        surname = rng.choice(SURNAMES)
        base = f"{first.lower()}_{surname.lower()[:3]}"
        agent_id = base
        n = 2
        while agent_id in taken:
            agent_id = f"{base}{n}"
            n += 1
        taken.add(agent_id)

        occupation, work, hours = rng.choice(trades)
        if occupation == "student":
            age = rng.randint(15, 19)
        elif occupation == "pensioner":
            age = rng.randint(64, 81)
        else:
            age = rng.randint(22, 61)

        # fill the emptiest houses first, so households form instead of
        # everyone living alone
        home = min(sorted(homes), key=lambda h: (occupied.get(h, 0), h))
        occupied[home] = occupied.get(home, 0) + 1

        out.append({
            "id": agent_id,
            "name": f"{first} {surname}",
            "age": age,
            "occupation": occupation,
            "traits": rng.sample(TRAITS, 3),
            "speech_tics": rng.sample(TICS, 1),
            "backstory": rng.choice(BACKSTORY).format(first=first),
            "home": home,
            "work": work,
            "vendor_of": [],
            "work_hours": list(hours) if hours else None,
            "faith": "catholic" if rng.random() < 0.08 else "muslim",
            "opinion": {"political_lean": round(rng.uniform(-0.7, 0.7), 2)},
            "relationships": {},
        })

    # Households know each other well; then a few acquaintances across the town.
    everyone = authored + out
    by_home: dict[str, list[dict]] = {}
    for a in everyone:
        by_home.setdefault(a["home"], []).append(a)
    for housemates in by_home.values():
        for a in housemates:
            for b in housemates:
                if a is b or b["id"] in a["relationships"]:
                    continue
                if a in out or b in out:
                    a["relationships"][b["id"]] = {
                        "affinity": round(rng.uniform(0.35, 0.8), 2),
                        "familiarity": round(rng.uniform(0.8, 1.0), 2),
                        "tag": "lives in the same house",
                    }
    pool = [a["id"] for a in everyone]
    for a in out:
        for other in rng.sample(pool, 3):
            if other == a["id"] or other in a["relationships"]:
                continue
            a["relationships"][other] = {
                "affinity": round(rng.uniform(-0.3, 0.6), 2),
                "familiarity": round(rng.uniform(0.1, 0.6), 2),
                "tag": rng.choice(TAGS),
            }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=30,
                    help="how many residents in all, authored included")
    ap.add_argument("--out", default="config/cast.json")
    args = ap.parse_args()

    authored = json.loads(
        Path("config/agents.json").read_text(encoding="utf-8"))["agents"]
    town = json.loads(Path("config/town.json").read_text(encoding="utf-8"))
    if args.total < len(authored):
        raise SystemExit(f"--total must be at least {len(authored)} (the authored cast)")

    generated = generate(authored, args.total, town)
    cast = authored + generated

    areas = {a["id"] for a in town["areas"]}
    ids = {a["id"] for a in cast}
    assert len(ids) == len(cast), "duplicate agent id"
    for a in cast:
        assert a["home"] in areas, f"{a['id']}: bad home {a['home']}"
        assert a["work"] is None or a["work"] in areas, f"{a['id']}: bad work {a['work']}"
        for r in a["relationships"]:
            assert r in ids, f"{a['id']}: relationship with unknown {r}"

    Path(args.out).write_text(
        json.dumps({"agents": cast}, ensure_ascii=False, indent=1), encoding="utf-8")

    households: dict[str, int] = {}
    for a in cast:
        households[a["home"]] = households.get(a["home"], 0) + 1
    trades: dict[str, int] = {}
    for a in cast:
        trades[a["occupation"]] = trades.get(a["occupation"], 0) + 1
    print(f"wrote {args.out}: {len(cast)} residents "
          f"({len(authored)} authored, {len(generated)} generated)")
    print(f"  households: {len(households)}, "
          f"{min(households.values())}-{max(households.values())} people each")
    print("  trades: " + ", ".join(f"{k} {v}" for k, v in sorted(trades.items())))


if __name__ == "__main__":
    main()
