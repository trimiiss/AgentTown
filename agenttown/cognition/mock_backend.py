"""The template backend: deterministic cognition with no model behind it.

This is not scaffolding. It is the fallback every real backend degrades to
when its budget runs out, so it must implement all five call types fully and
return the same validated shapes. Being deterministic, it is also what makes
the replay test meaningful.
"""

from __future__ import annotations

from ..memory.importance import heuristic_importance
from ..sim.rng import stream
from .backend import (
    ConverseRequest,
    ImportanceRequest,
    PlanRequest,
    ReactRequest,
    ReflectRequest,
)
from .schemas import (
    ActionProposal,
    Conversation,
    DailyPlan,
    GossipItem,
    ImportanceScores,
    PlanItem,
    Reaction,
    Reflection,
    Utterance,
)

SOCIAL_PLACES = ("kafiteria", "pazari", "parku")
VENDOR_AREA = {"bread": "furra", "coffee": "kafiteria",
               "cigarettes": "dyqani", "medicine": "ambulanca"}
AREA_VENDOR = {v: k for k, v in VENDOR_AREA.items()}
VENDOR_AGENT = {"furra": "agim", "kafiteria": "arben",
                "dyqani": "shpend", "ambulanca": "luljeta"}


def first(name: str) -> str:
    return name.split()[0]


def _pray_at(faith: str) -> str:
    return "kisha" if faith == "catholic" else "xhamia"


# --------------------------------------------------------------------------
# Conversation templates: ("a"|"b", text) with {A} {B} {item} {price} {place}
# {claim} {occ} slots. Two to four turns, produced in one call.
# --------------------------------------------------------------------------
TOPIC_TURNS: dict[str, list[list[tuple[str, str]]]] = {
    "prices": [
        [("a", "Have you heard what {item} costs now? {price} euro."),
         ("b", "I heard. Everything climbs and the wages sit exactly where they were."),
         ("a", "My father sold a whole sack of flour for less than that."),
         ("b", "Po, po. And not one word about it at the komuna.")],
        [("a", "{price} euro for {item}. Tell me that is reasonable."),
         ("b", "It is not. But what will you do, stop eating?"),
         ("a", "I will complain. Complaining is still free.")],
        [("b", "You have the face of a man who has just seen a price."),
         ("a", "{item}. {price}. In this town."),
         ("b", "Ani, ani. Next week it will be more.")],
    ],
    "gossip": [
        [("a", "A ke marre vesh? They are saying {claim}."),
         ("b", "Who told you that?"),
         ("a", "It is going around Carshia. Believe what you like."),
         ("b", "I will believe it when I see it with my own eyes.")],
        [("a", "Keep this between us. {claim}."),
         ("b", "In this town? Nothing stays between two people."),
         ("a", "Then you did not hear it from me.")],
        [("b", "You look like you are carrying news."),
         ("a", "Only that {claim}."),
         ("b", "Hm. That would explain a few things.")],
    ],
    "politics": [
        [("a", "If there is a vote next week, I know exactly where mine goes."),
         ("b", "You always know. That has always been your trouble."),
         ("a", "Better than knowing nothing and calling it balance.")],
        [("a", "Did you read what the komuna put up on the board?"),
         ("b", "I read it. It says nothing, very carefully."),
         ("a", "That is the whole art of it.")],
        [("b", "They will promise the road again."),
         ("a", "They promised that road in my first year of school."),
         ("b", "And here we are, still stepping around the same hole.")],
    ],
    "health": [
        [("b", "You look tired. Are you sleeping at all?"),
         ("a", "I sleep. Ngadale, I am not finished yet."),
         ("b", "Come by the ambulanca anyway. It costs you nothing.")],
        [("a", "My knee again, with this weather."),
         ("b", "Then stop standing on it all day and come and see me."),
         ("a", "When there is time.")],
    ],
    "work": [
        [("a", "Busy today?"),
         ("b", "Since before you were awake."),
         ("a", "Somebody has to keep this street moving.")],
        [("a", "How is it going, bre?"),
         ("b", "The same as yesterday, only later.")],
        [("b", "You are out early."),
         ("a", "The work does not come to the house.")],
    ],
    "family": [
        [("a", "Did you eat anything today, or only coffee?"),
         ("b", "There was bread."),
         ("a", "Bread is not a meal. Come home at a reasonable hour.")],
        [("a", "Any word from the ones abroad?"),
         ("b", "Money came. A telephone call did not."),
         ("a", "That is how it goes now.")],
    ],
    "smalltalk": [
        [("a", "Cold on the street this morning."),
         ("b", "It will turn by noon. It always does.")],
        [("a", "Quiet today."),
         ("b", "Give it an hour. It is never quiet for long here.")],
        [("b", "Going up to the pazar?"),
         ("a", "Later, if the day lets me.")],
        [("a", "They still have not fixed the light by the school."),
         ("b", "They will, the week after somebody falls in the dark.")],
    ],
    "school": [
        [("a", "Have you done the reading?"),
         ("b", "Most of it."),
         ("a", "Most of it is how people end up staying here.")],
        [("b", "Will you really go to Prishtina?"),
         ("a", "Po, po. The week after the exams.")],
    ],
}

TOPIC_VALENCE = {"prices": -0.35, "gossip": -0.10, "politics": -0.30, "health": 0.20,
                 "work": 0.10, "family": 0.30, "smalltalk": 0.10, "school": 0.15}

MONEY_WORDS = ("price", "prices", "euro", "expensive", "cheaper", "raised", "costs")

THEMES: dict[str, tuple[str, ...]] = {
    "money": MONEY_WORDS + ("money", "paid", "owes", "wage", "flour"),
    "health": ("fever", "ill", "sick", "nurse", "medicine", "tired", "knee"),
    "politics": ("election", "vote", "komuna", "candidate", "mayor", "promised"),
    "faith": ("prayed", "xhamia", "kisha", "church", "mosque"),
    "work": ("worked", "shift", "customers", "class", "taught", "sold", "loaf"),
    "people": ("told", "said", "met", "talked", "asked"),
}

INSIGHTS: dict[str, tuple[str, ...]] = {
    "money": ("This town is getting more expensive than it will admit.",
              "I think about money more often than I used to.",
              "Nobody here is keeping up with the prices."),
    "health": ("People wait far too long before they come in.",
               "My body is keeping a list of its own complaints."),
    "politics": ("Whoever wins, the road will stay exactly as it is.",
                 "I have started paying attention to the komuna again.",
                 "People here vote with their grievances, not their hopes."),
    "faith": ("The quiet at prayer is the only part of my day nobody wants.",
              "Faith is habit as much as belief, and I have made peace with that."),
    "work": ("The work is steady, and that is its own kind of luck.",
             "I am tired in a way that sleep does not reach."),
    "people": ("News travels faster here than anything else does.",
               "I know more about this street than about my own family.",
               "Being known by everyone is not the same as being close to anyone."),
}

SUMMARY = ("{name} is {age}, {occ} in a town where everybody is counted. "
           "Lately it has been about {theme}. There is {money} euro in the house. "
           "{tired}{lonely}Underneath, the same person.")


class MockBackend:
    """Deterministic, zero-cost, and fully schema-conformant."""

    name = "mock"
    model = "mock"

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.calls: dict[str, int] = {}

    def _count(self, kind: str) -> None:
        self.calls[kind] = self.calls.get(kind, 0) + 1

    # --- 1. daily plan -------------------------------------------------
    def daily_plan(self, req: PlanRequest) -> DailyPlan:
        self._count("daily_plan")
        rng = stream(self.seed, "plan", req.agent.id, req.day)
        a = req.agent
        home, pray = a.home, _pray_at(a.faith)
        social = rng.choice(SOCIAL_PLACES)
        items: list[tuple[int, str, str, str]] = []

        if a.work and req.work_hours:
            h0, h1 = req.work_hours
            items.append((max(0, min(h0 - 1, 9)), "eat", home, "breakfast standing up"))
            items.append((h0, "work", a.work, "open up"))
            if "bread" not in a.vendor_of:
                items.append((min(max(h0 + 1, 11), h1), "buy_bread", "furra",
                              "bread for the house"))
            items.append((h1, rng.choice(["buy_coffee", "socialize"]), social,
                          "after the shift"))
            items.append((min(h1 + 3, 21), "eat", home, "dinner"))
            if "devout" in a.traits or a.occupation in ("imam", "priest"):
                items.append((13, "pray", pray, ""))
        elif a.occupation == "student":
            items.append((7, "eat", home, "breakfast"))
            items.append((8, "study", "shkolla", "class"))
            items.append((14, "socialize", rng.choice(("pazari", "parku")),
                          "after school"))
            items.append((17, "buy_cigarettes", "dyqani", "on credit again"))
            items.append((19, "eat", home, "dinner"))
        else:
            items.append((7, "eat", home, "breakfast"))
            items.append((8, "buy_bread", "furra", "the morning loaf"))
            items.append((10, "pray", pray, ""))
            items.append((12, "shop", "pazari", "see who is about"))
            items.append((16, "socialize", social, ""))
            items.append((19, "eat", home, "dinner"))

        items.append((22 if rng.random() < 0.7 else 23, "sleep", home, ""))
        return DailyPlan(items=[
            PlanItem(start_hour=max(0, min(23, h)), affordance=aff, area=area, note=note)
            for h, aff, area, note in items
        ])

    # --- 2. conversation ----------------------------------------------
    def converse(self, req: ConverseRequest) -> Conversation:
        self._count("converse")
        rng = stream(self.seed, "talk", req.a.id, req.b.id, req.tick)
        a, b = req.a, req.b
        topic = self._pick_topic(req, rng)

        money_mem = next((m for m in req.a_memories
                          if any(w in m.lower() for w in MONEY_WORDS)), "")
        item = next((k for k in sorted(req.prices) if k in money_mem.lower()), "bread")
        price = f"{req.prices.get(item, 0.5):.2f}"
        claim = req.a_gossip[0].get("sentence", "something is going on") \
            if req.a_gossip else "something"

        template = rng.choice(TOPIC_TURNS[topic])
        keep = max(2, min(req.max_turns, len(template)))
        turns: list[Utterance] = []
        for who, text in template[:keep]:
            speaker = a if who == "a" else b
            other = b if who == "a" else a
            turns.append(Utterance(speaker=speaker.id, text=text.format(
                A=first(a.name), B=first(b.name), item=item, price=price,
                place=req.place, claim=claim, occ=other.occupation)))

        sentiment = max(-1.0, min(1.0, 0.5 * a.affinity + TOPIC_VALENCE[topic]
                                  + rng.uniform(-0.15, 0.15)))
        return Conversation(turns=turns,
                            gossip=self._make_gossip(req, topic, item, rng),
                            sentiment=round(sentiment, 3), topic=topic)

    def _pick_topic(self, req: ConverseRequest, rng) -> str:
        a, b = req.a, req.b
        joined = " ".join(req.a_memories).lower()
        if req.a_gossip and rng.random() < 0.70:
            return "gossip"
        if any(w in joined for w in MONEY_WORDS) and rng.random() < 0.80:
            return "prices"
        if abs(a.political_lean - b.political_lean) > 0.60 and rng.random() < 0.50:
            return "politics"
        if "nurse" in (a.occupation, b.occupation) and rng.random() < 0.60:
            return "health"
        if b.relationship_tag in ("wife", "husband", "brother", "sister") or (
                a.affinity > 0.60 and rng.random() < 0.50):
            return "family"
        if "student" in (a.occupation, b.occupation) and rng.random() < 0.50:
            return "school"
        return "work" if rng.random() < 0.45 else "smalltalk"

    def _make_gossip(self, req: ConverseRequest, topic: str, item: str,
                     rng) -> GossipItem | None:
        """A conversation either passes a rumour on, distorting it, or starts one."""
        if topic == "gossip" and req.a_gossip:
            g = req.a_gossip[0]
            truth = bool(g.get("truth_value", True))
            return GossipItem(
                subject=g.get("subject", ""),
                predicate=g.get("predicate", "is said to have"),
                object=g.get("object", "something"),
                truth_value=(not truth) if rng.random() < 0.18 else truth,
                distortion=int(g.get("distortion", 0)) + 1,
                topic=g.get("topic", "general"),
            )
        if topic == "prices" and rng.random() < 0.60:
            return GossipItem(
                subject=VENDOR_AGENT.get(VENDOR_AREA.get(item, "furra"), ""),
                predicate="has put up the price of", object=item,
                truth_value=True, distortion=0, topic="prices")
        if topic == "politics" and rng.random() < 0.35:
            return GossipItem(
                subject="blerim", predicate="is angling for",
                object="the top job at the komuna",
                truth_value=rng.random() < 0.6, distortion=0, topic="politics")
        return None

    # --- 3. reflection -------------------------------------------------
    def reflect(self, req: ReflectRequest) -> Reflection:
        self._count("reflect")
        rng = stream(self.seed, "reflect", req.agent.id, req.tick)
        joined = " ".join(req.memories).lower()
        ranked = sorted(THEMES, reverse=True,
                        key=lambda t: sum(joined.count(w) for w in THEMES[t]))
        chosen = [t for t in ranked if any(w in joined for w in THEMES[t])][:3] or ["people"]

        insights = [rng.choice(INSIGHTS[t]) for t in chosen]
        if req.memories:
            quote = req.memories[0].rstrip(".")
            if len(quote) > 110:
                quote = quote[:107].rsplit(" ", 1)[0] + "..."
            insights.append("What stays with me: " + quote + ".")

        a = req.agent
        summary = SUMMARY.format(
            name=first(a.name), age=a.age, occ=a.occupation.replace("_", " "),
            theme=", ".join(chosen), money=f"{a.money:.2f}",
            tired="Tired. " if a.needs.get("fatigue", 0.0) > 0.6 else "",
            lonely="Seeing too few people. " if a.needs.get("loneliness", 0.0) > 0.6 else "",
        )
        return Reflection(insights=insights[:4], self_summary=summary)

    # --- 4. reaction ---------------------------------------------------
    def react(self, req: ReactRequest) -> Reaction:
        self._count("react")
        rng = stream(self.seed, "react", req.agent.id, req.tick)
        a = req.agent
        nosy = any(t in a.traits for t in ("talkative", "knows everything first",
                                           "incurably curious", "restless"))

        if req.trigger_kind == "price_change":
            item = str(req.trigger_payload.get("item", "bread"))
            if item in a.vendor_of:
                return Reaction(interrupt=False,
                                thought="They will complain. Let them complain.")
            if rng.random() < (0.80 if nosy else 0.50):
                if item == "bread" and a.needs.get("hunger", 0.0) > 0.30:
                    return Reaction(
                        interrupt=True,
                        proposal=ActionProposal(
                            affordance="buy_bread", area="furra",
                            reason="buy " + item + " before it climbs again"),
                        thought=item + " at that price. Better go now.")
                return Reaction(
                    interrupt=True,
                    proposal=ActionProposal(
                        affordance="socialize", area="kafiteria",
                        reason="tell somebody about the " + item + " price"),
                    thought="Somebody has to hear about the " + item + ".")
            return Reaction(interrupt=False, thought="Prices go up. They always do.")

        if req.trigger_kind in ("election_called", "announcement"):
            if rng.random() < (0.85 if nosy else 0.45):
                return Reaction(
                    interrupt=True,
                    proposal=ActionProposal(affordance="socialize", area="kafiteria",
                                            reason="hear what people make of it"),
                    thought="This will be all anyone talks about.")
            return Reaction(interrupt=False, thought="I will hear about it soon enough.")

        if req.trigger_kind == "power_cut":
            return Reaction(
                interrupt=True,
                proposal=ActionProposal(affordance="idle", area=a.home,
                                        reason="nothing works without power"),
                thought="Again. The whole street is dark.")

        if req.trigger_kind == "rumour" and nosy:
            return Reaction(
                interrupt=True,
                proposal=ActionProposal(affordance="socialize", area="pazari",
                                        reason="find out whether it is true"),
                thought="I want to know who started that.")

        return Reaction(interrupt=False, thought="")

    # --- 5. batched importance ----------------------------------------
    def score_importance(self, req: ImportanceRequest) -> ImportanceScores:
        self._count("score_importance")
        return ImportanceScores(scores={
            mid: heuristic_importance(text, kind) for mid, kind, text in req.items
        })
