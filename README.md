# AgentTown

A small Kosovar town, simulated. **Thirty residents** — twelve hand-written,
eighteen generated — hold jobs, relationships, money and daily routines,
remember what happens to them, gossip, hold an election, and react to events
you inject: "the bakery raises prices", "election next week". You watch it
happen on a 2D map in the browser.

It follows Stanford's [*Generative Agents*](https://arxiv.org/abs/2304.03442)
but deliberately diverges on the two things that make that paper impractical to
run: per-agent-per-tick model calls, and unbounded memory growth.

```bash
uv sync
uv run uvicorn agenttown.main:app --port 8000     # then open http://localhost:8000
uv run pytest                                      # 106 tests, ~70s
```

Out of the box it runs on a **template backend** with no model behind it, so it
costs nothing and is fully deterministic. Switching to real Claude calls is one
line of config — see *Running on real Claude* below.

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

Measured at **30 agents over 15 sim-days**: **100% of ~3,700 decisions never
reached a model**; the policy cache reaches a **70% hit rate** by day 15 and
**92% by day 120**. Total model traffic is **~89 calls per sim-day**, i.e. ~3
per agent per sim-day — it scales with the number of agents, not with ticks.

Priced as `claude-haiku-5-5` ($0.10/$0.50 per MTok) on the real token counts of
the prompts actually built: **$0.008 per simulated day at 30 agents**. Cents per
simulated week.

Runtime is **~2 ms/tick at 30 agents** (≈500 ticks/s), against the 10 ticks/s
the UI asks for — roughly 50× headroom.

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
day. Measured: **~19 per agent per sim-day**, stable from day 20 to day 120.
The in-RAM working set is capped per agent with LRU eviction back to SQLite;
eviction starts biting around day 80 and by day 120 has moved ~33,000 memories
out of RAM while SQLite keeps all of them.

### The economy has to be bounded, not just conserved

Money is conserved except at declared sources (wages, diaspora remittances) and
sinks, and a test asserts an imbalance of zero. That alone is not enough: the
first version conserved money perfectly while the baker climbed past 400 euro
and kept going, because he sold to everyone and nothing drained him. Three
mechanisms give it a steady state:

- **cost of goods** — 40% of every sale leaves town to the wholesaler. It has to
  be per-sale; a flat daily charge stops working the moment the town grows more
  customers.
- **the self-employed earn a margin, not a wage** — paying the baker both made
  him inflate. `economy.wages` is `0.0` for baker, cafe owner and shopkeeper,
  and a test enforces it.
- **spending rises with means** — a small wealth-proportional daily cost, which
  is what turns linear growth into convergence.

Over 120 sim-days the richest agent plateaus around 240 while the median holds
near 25 and the money imbalance stays at zero.

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

What actually happened when bread went from 0.50 to 0.95 at 30 agents: all
thirty got a `react` call and **eighteen dropped what they were doing**; Agim
the baker declined (*"They will complain. Let them complain."*) while the
talkers went looking for someone to tell; stale "go to the furra" habits were
invalidated in the policy cache; and several agents **stocked up**, so bread
purchases briefly went *up* 13%. Over a week the rumour reached 29 of 30
residents and **turned false** on the way.

## Running on real Claude

```toml
# config/sim.toml
[cognition]
backend = "claude"
model = "claude-haiku-5-5"
```

Then set `ANTHROPIC_API_KEY`, or run `ant auth login` — the SDK resolves either,
and no key is ever written into the project. `make_backend()` in
`agenttown/sim/loop.py` is the entire switch.

Three things make it cheap, and one makes it safe:

- **The prefix is cached.** The world vocabulary (every place, person and legal
  action) plus the agent's identity card are byte-stable for a whole run, so
  they go in `system` behind a `cache_control` breakpoint. Measured on a real
  planning prompt: **613 cached tokens against 87 volatile ones** — 87% of the
  input is served at a tenth of the price after the first call.
- **Effort is low.** These are short in-character utterances, not reasoning
  problems; `output_config.effort` is the first lever, ahead of model choice.
- **Output is schema-constrained.** `output_config.format` with a strict JSON
  schema, so there is no parsing heuristic and no retry for malformed JSON.
- **Every failure degrades.** An API error, a refusal, a timeout, a truncation,
  an unparseable body, a hallucinated affordance — all of them fall through to
  the template backend instead of raising, so the town keeps running. Each is a
  separate test, and one of them runs a whole sim-day against a backend that
  fails every single call.

The world vocabulary in the cached prefix is not decoration: without it a real
model invents places, and the validator throws the output away. Telling it what
exists costs nothing per call because it is cached.

The backend is tested offline against a scripted transport — no network, no key,
no spend — which still pins down the cache-breakpoint placement, prefix
stability, schema strictness and every degradation path.

**On the Batch API:** the cost model supports its 50% discount
(`budget.record(..., batched=True)`), but it is not used for `daily_plan`. A
batch has no latency guarantee, and an agent needs its plan on the tick it
wakes up. `score_importance` is the one call where latency genuinely does not
matter, so that is where batching belongs when it is added.

## The election

`election_called` adds no special case to the agent loop. It sets a date and
names candidates; everything after that runs on machinery that already existed:

- **Candidates are the best-known person on each side of the argument** —
  notoriety is summed from everybody else's familiarity, so the field is
  whoever the town already has an opinion about, not a random pick.
- **Opinion moves through conversation.** A warm political exchange pulls two
  people together; a sour one pushes them apart. Each person is also pulled
  gently back toward where they started, so the town cannot saturate at total
  polarisation after a bad week.
- **Rumours have consequences.** A rumour about a candidate that has turned
  false costs them support with whoever heard it.
- **Voting is an affordance.** The komuna already had a ballot box with a
  `vote` affordance; voters walk there and use it like any other object.
- **Turnout is earned**, from strength of opinion and how much politics someone
  has actually talked about. It is never total, and some people who mean to
  vote never get there.

A measured 13-day campaign: polarisation climbed 0.348 → 0.590, turnout came in
at **80%** — against 60% for a 3-day campaign, because a longer campaign means
more political conversations means more engagement. That relationship is not
coded anywhere. Ties are detected and reported as ties.

The **Election** tab charts support per candidate over the campaign,
polarisation, and the final count, with a table beside the bars so the result
never depends on reading colour. Polarisation is the standard deviation of
opinion, not its range — with thirty residents, two hardliners peg a range
measure at its ceiling and it stops telling you anything.

## Layout

```
config/sim.toml          seed, tick rate, budgets, retrieval weights, economy
config/agents.json       the 12 authored characters - hand-edit this one
config/cast.json         all 30 residents, generated by tools/make_cast.py
config/town.json         generated by tools/make_town.py (self-verifying)
config/scenarios/        injectable event bundles
agenttown/world/         grid, A*, affordances, economy
agenttown/agents/        state, needs, relationships, routines (tiers 0-1), policy cache
agenttown/cognition/     the backend seam, schemas + validator, prompts, budget,
                         mock backend, claude backend
agenttown/memory/        store, embeddings, retrieval, importance
agenttown/sim/           loop, events, gossip, election, recorder, rng
agenttown/web/           canvas UI and SVG charts, no build step
```

Neither the map nor the cast is hand-written:

```bash
uv run python tools/make_town.py              # asserts connectivity before writing
uv run python tools/make_cast.py --total 40   # 12 authored + 28 generated
```

`make_town.py` asserts row widths, door walkability, object placement and full
connectivity, so a broken map fails there rather than at simulation time.
`make_cast.py` never writes to `config/agents.json`, so the authored characters
cannot be clobbered.

## Where this goes next

- **A/B the mock against Claude on the same seed.** Everything needed is in
  place: run the same seed on both backends and diff the tick logs to see
  exactly what the model buys you over templates. Nobody has run this yet
  because it needs a key.
- **A local backend.** `make_backend()` has the slot. On a machine with more
  than ~6 GB of RAM, a 2B-class model at Q4 could take the highest-volume call
  types (`converse`) while Claude keeps planning and reflection.
- **Batch the importance rescoring**, as described above — the one call where
  latency genuinely does not matter, for half price.
- **More scenarios.** Events are a closed, declarative set, so a scenario is a
  JSON file: a factory closure, a returning diaspora family, a drought.

### Known rough edges

- Agents walk 3 tiles/tick (`sim.walk_speed`). At 1 tile/tick a tick is 10
  sim-minutes and crossing town costs 5 sim-hours, which starves the day of
  activity — worth remembering before retuning the clock.
- By day 120 about 7% of purchase attempts are refused for want of money. That
  is a town where the poor sometimes cannot afford bread, which is honest, but
  it is at the edge of what the current wage and support numbers sustain.
- Nobody buys medicine often, so Luljeta the nurse runs closer to broke than
  her job suggests. The `ambulanca` wants a reason to be visited.
- Conversation topic choice is keyed off the speakers' occupations, so the
  templates occasionally put a line in a slightly odd mouth. A real backend
  removes this.
- The Claude backend has never run against the live API — there was no key on
  the machine it was built on. It is covered by 24 offline tests against a
  scripted transport, but the first real call may still surprise you. Start
  with the budget ceilings low.
- Starting a second server while one is running fails with a clear error rather
  than silently sharing a database. On Windows, stop the first one properly —
  `pkill` does not reach it; use Task Manager or PowerShell's `Stop-Process`.
