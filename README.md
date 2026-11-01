# AgentTown

A small Kosovar town, simulated. Nine residents (scaling to 20–50) hold jobs,
relationships, money and daily routines, remember what happens to them, gossip,
and react to events you inject — "the bakery raises prices", "election next
week". You watch it happen on a 2D map in the browser.

It follows Stanford's [*Generative Agents*](https://arxiv.org/abs/2304.03442)
but deliberately diverges on the two things that make that paper impractical to
run: per-agent-per-tick model calls, and unbounded memory growth.

```bash
uv sync
uv run uvicorn agenttown.main:app --port 8000     # then open http://localhost:8000
uv run pytest                                      # 54 tests, ~6s
```

Out of the box it runs on a **template backend** with no model behind it, so it
costs nothing and is fully deterministic.

---

## The two hard problems, and what this does about them

### Cost: tiering, not a smaller model

A naive generative-agent simulation calls the model for every agent on every
tick. Here, every decision resolves at the cheapest tier that can answer it:

| Tier | What answers | Model? |
|---|---|---|
| **0 — reflex** | walking, need decay, affordance effects, transactions | no |
| **1 — policy cache** | what this agent did last time the situation looked like this, keyed by a coarse `(occupation, hour/3, dominant need, area kind, company)` tuple | no |
| **2 — model** | exactly five call types, below | yes |

Measured over 20 sim-days with 9 agents: **100% of ~1,500 decisions never
reached a model**, and the policy cache settles around a **60% hit rate**. Total
model traffic is **~19 calls per sim-day**, i.e. ~2 per agent per sim-day — it
scales with the number of agents, not with ticks.

Priced as `claude-haiku-5-5` ($0.10/$0.50 per MTok) using the real token counts
of the prompts actually built: **~$0.002 per simulated day at 9 agents**, about
**$0.007 at 30**. Cents per sim-week, not dollars per sim-day.

The only five permitted call types — nothing else may call out:

- `daily_plan` — once per agent per sim-day
- `converse` — a whole 2–4 turn exchange **plus** a typed gossip payload in one
  call, not one call per utterance
- `reflect` — when accumulated importance crosses a threshold
- `react` — when an injected event lands
- `score_importance` — **batched**, 10–20 memories per call, and only for the
  ambiguous middle band; a keyword heuristic handles the rest for free

`config/sim.toml` sets a per-sim-day ceiling on each. Hitting a ceiling does not
fail the call — it **degrades to the template backend**, which is the same code
path the whole simulation was built on. That is why the mock is permanent
infrastructure rather than scaffolding.

### Consistency: the engine owns the truth

Money, position, inventory, relationships, needs and prices are typed fields the
engine writes. A backend only ever *proposes*, and five things keep an agent
recognisably itself across sim-days:

1. **Identity card** — derived only from immutable seed data, byte-identical on
   every call, so it sits behind a prompt-cache breakpoint. A test asserts that
   volatile state never leaks into it.
2. **Rolling self-summary** — ~120 words, rewritten only on reflection. Bounded
   length means bounded drift.
3. **Structured facts over prose** — the model can describe money; it cannot
   author it.
4. **Closed-world validator** — output must name an affordance, area and person
   that exist. Fed a deliberately hostile backend, the validator logged **63
   rejections** across plan items, utterances, gossip and action proposals while
   money stayed conserved and no agent left the map.
5. **Typed gossip** — `(subject, predicate, object, truth_value, distortion)`,
   so rumours mutate in measurable ways rather than as free text.

### Memory

One SQLite row per remembered thing. Retrieval scores
`recency + importance + relevance`, each min-max normalised across candidates
before the weighted sum, so the inspector can show *why* a memory surfaced.
Embeddings are a signed hashing-trick projection of unigrams and bigrams — a
real, deterministic lexical retriever that needs no model, so retrieval quality
is testable before any tokens are bought.

**Observation gating is mandatory.** Writing an observation every tick would be
~144 per agent per sim-day and would drown retrieval. Observations are written
only on change — a completed *memorable* affordance, a first sighting in a
place, a conversation, an event — capped at two per `(affordance, area)` per
day. Measured: **~13 per agent per sim-day**. The in-RAM working set is capped
per agent with LRU eviction back to SQLite.

### Determinism

One seed, per-agent RNG streams derived through blake2b from
`(seed, who, when)`, agents always processed in sorted id order, and a
byte-canonical JSONL tick log. Same seed ⇒ identical run digest; this is the
first test in the suite, because without it you cannot ask *why did that
emerge?* and get an answer.

---

## Watching it

The frontend is plain ES modules and a canvas served by FastAPI — **no npm, no
bundler, no second dev server**.

- **Map** — click anybody. Speech bubbles stage one turn at a time.
- **Agent** — identity, needs, current action *with the tier that decided it*,
  today's plan, relationships, rumours carried, the rolling self-summary, the
  identity card, and the **top-10 retrieved memories with their per-component
  score breakdown**.
- **Talk / Rumours** — the conversation feed, and a board showing how far each
  rumour has travelled, its distortion count, and whether it has turned false.
- **Inject** — the bundled scenarios, or a one-off event as raw JSON.
- **Cost** — the tier split, call counts against ceilings, degraded-call count,
  token totals and the priced-as-Haiku figure.

`Space` pauses, `.` steps one tick.

## Injecting events

Events have **no special-case code path**. Injecting one writes a world variable
at most, and writes a high-importance observation into the memory streams of the
agents in scope. Reactions, conversations and reflections then follow from the
ordinary rules — which is why "the bakery raises prices" produces talk about
bread without a line of bread-talk code.

```bash
curl -X POST localhost:8000/api/scenarios/bakery_prices
curl -X POST localhost:8000/api/events -H 'content-type: application/json' \
     -d '{"kind":"price_change","payload":{"item":"coffee","factor":1.4}}'
```

Kinds: `price_change`, `announcement`, `election_called`, `power_cut`, `rumour`,
`arrival`, `weather`, `remittance`. `scope` is `town`, an area id, or an agent
id — scoping an event to one area instead of the town is the interesting
experiment, because then it has to *travel*.

What actually happened when bread went from 0.50 to 0.95: all nine agents held
it at importance 8.0 and all nine retrieved it; Agim the baker declined to react
(*"They will complain. Let them complain."*) while Arben the gossip went looking
for someone to tell; three stale "go to the furra" habits were invalidated; and
several agents **stocked up**, so purchases briefly went *up*. Over eight
sim-days the rumour reached all nine and **turned false** after five retellings.

## Layout

```
config/sim.toml          seed, tick rate, budgets, retrieval weights, economy
config/town.json         generated by tools/make_town.py (self-verifying)
config/agents.json       the cast
config/scenarios/        injectable event bundles
agenttown/world/         grid, A*, affordances, economy
agenttown/agents/        state, needs, relationships, routines (tiers 0-1), policy cache
agenttown/cognition/     the backend seam, schemas + validator, prompts, budget, mock
agenttown/memory/        store, embeddings, retrieval, importance
agenttown/sim/           loop, events, gossip, recorder, rng
agenttown/web/           canvas UI, no build step
```

The map is generated, not hand-written: `uv run python tools/make_town.py`
asserts row widths, door walkability, object placement and full connectivity
before writing, so a broken map fails there rather than at simulation time.

## Where this goes next

- **Scale** to 20–50 agents: `config/agents.json` is the only thing that needs
  to grow. Twelve hand-authored characters plus templated residents.
- **A real backend**: implement `claude_backend.py` against the
  `LLMBackend` protocol in `agenttown/cognition/backend.py`. The prompts, the
  cache breakpoint, the budget, the validator and the degradation path already
  exist; `make_backend()` in `agenttown/sim/loop.py` is the one switch. A/B it
  against the mock on the same seed to see what the model actually buys.
- **Election scenario** end to end: `opinion.political_lean` already drifts
  through conversation, and the komuna has a ballot box with a `vote`
  affordance.

### Known rough edges

- Agents walk 3 tiles/tick (`sim.walk_speed`). At 1 tile/tick a tick is 10
  sim-minutes and crossing town costs 5 sim-hours, which starves the day of
  activity — worth remembering before retuning the clock.
- Wealth spreads realistically but one agent (usually Luljeta, the nurse —
  almost nobody buys medicine) tends to sit near zero. Balance, not a bug, but
  the wage and price tables in `config/sim.toml` deserve another pass.
- Conversation topic choice is keyed off the speakers' occupations, so the
  templates occasionally put a line in a slightly odd mouth. A real backend
  removes this.
