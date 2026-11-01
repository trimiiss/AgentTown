// The side panels. The agent inspector is the important one: it shows not just
// what an agent is doing but WHY - the retrieved memories and the per-component
// score that put them in front of the decision.

import { agentColour } from "./render.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const pct = (v) => `${Math.round(v * 100)}%`;

function needBar(label, value, invert = false) {
  const cls = invert ? (value > 0.6 ? "good" : "") : value > 0.75 ? "hot" : "";
  return `<div class="need"><span>${label}</span>
    <span class="track"><span class="fill ${cls}" style="width:${pct(value)}"></span></span>
    <var>${value.toFixed(2)}</var></div>`;
}

export function renderAgent(el, d, town) {
  if (!d || !d.id) {
    el.innerHTML = '<p class="hint">Click somebody on the map.</p>';
    return;
  }
  const areaName = (id) => {
    const a = town.areas.find((x) => x.id === id);
    return a ? a.name : id;
  };
  const act = d.action;

  el.innerHTML = `
    <h2 style="color:${agentColour(d.id)}">${esc(d.name)}</h2>
    <p class="sub">${d.age}, ${esc(d.occupation.replace("_", " "))} &middot;
       at ${esc(d.here)} &middot; ${d.money.toFixed(2)} euro</p>
    <p class="story">${esc(d.backstory)}</p>
    <div class="tags">${d.traits.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>

    <h3>Right now</h3>
    ${act ? `<dl class="kv">
      <dt>doing</dt><dd>${esc(act.affordance)}</dd>
      <dt>where</dt><dd>${esc(areaName(act.area))}</dd>
      <dt>because</dt><dd>${esc(act.reason)}</dd>
      <dt>decided by</dt><dd>${esc(act.tier)}${act.tier === "llm" ? " (reaction)" : ""}</dd>
      <dt>ticks left</dt><dd>${act.ticks_left}${act.arrived ? "" : " (walking)"}</dd>
    </dl>` : '<p class="hint">deciding...</p>'}
    ${d.last_thought ? `<p class="story" style="margin-top:8px">
       &ldquo;${esc(d.last_thought)}&rdquo;</p>` : ""}

    <h3>Needs</h3>
    ${needBar("hunger", d.needs.hunger)}
    ${needBar("fatigue", d.needs.fatigue)}
    ${needBar("loneliness", d.needs.loneliness)}
    ${needBar("mood", d.needs.mood, true)}

    <h3>Lately (rolling self-summary)</h3>
    <p class="story">${esc(d.self_summary) || "<i>has not reflected yet</i>"}</p>

    <h3>Retrieved for this decision</h3>
    <p class="hint" style="font-size:11px">
      query: &ldquo;${esc(d.retrieval_query)}&rdquo; &middot;
      ${d.memory_count} memories held, ${d.working_set} in RAM</p>
    ${d.retrieved.map(memHtml).join("") || '<p class="hint">nothing yet</p>'}

    <h3>Plan for today</h3>
    ${d.plan.length ? `<dl class="kv">${d.plan.map((p) => `
      <dt style="${p.done ? "opacity:.4" : ""}">${String(p.start_hour).padStart(2, "0")}:00</dt>
      <dd style="${p.done ? "opacity:.4;text-decoration:line-through" : ""}">
        ${esc(p.affordance.replace("_", " "))} &middot; ${esc(areaName(p.area))}
        ${p.note ? `<span class="muted">- ${esc(p.note)}</span>` : ""}</dd>`).join("")}
      </dl>` : '<p class="hint">no plan yet</p>'}

    <h3>Relationships</h3>
    <dl class="kv">${Object.entries(d.relationships)
      .sort((a, b) => b[1].familiarity - a[1].familiarity)
      .map(([id, r]) => `<dt style="color:${agentColour(id)}">${esc(id)}</dt>
        <dd>${r.affinity >= 0 ? "+" : ""}${r.affinity.toFixed(2)}
        <span class="muted">fam ${r.familiarity.toFixed(2)} &middot;
        ${r.conversations} talks${r.tag ? ` &middot; ${esc(r.tag)}` : ""}</span></dd>`)
      .join("")}</dl>

    ${d.insights.length ? `<h3>Reflections</h3>
      ${d.insights.slice().reverse().map((i) =>
        `<div class="mem reflection"><p>${esc(i)}</p></div>`).join("")}` : ""}

    ${d.known_gossip.length ? `<h3>Rumours carried</h3>
      ${d.known_gossip.map((g) => `<div class="mem">
        <p>${esc(g.sentence)}</p>
        <div class="bars">heard from ${esc(g.from)} &middot;
          distortion ${g.distortion} &middot;
          <span class="${g.truth_value ? "" : "false"}" style="color:${
            g.truth_value ? "inherit" : "var(--warn)"}">
            ${g.truth_value ? "believes it true" : "believes it false"}</span>
        </div></div>`).join("")}` : ""}

    <h3>Identity card (the cached prompt prefix)</h3>
    <div class="mem"><p style="font-family:var(--mono);font-size:10.5px;
      white-space:pre-wrap">${esc(d.prompt)}</p></div>
    <p class="note">This block is byte-identical on every call for this agent,
      which is what lets it sit behind a prompt-cache breakpoint.</p>
  `;
}

function memHtml(m) {
  const b = m.breakdown;
  const w = (v) => `${Math.max(2, Math.round(v * 46))}px`;
  return `<div class="mem ${m.kind}">
    <p>${esc(m.text)}</p>
    <div class="bars">
      <em class="rec" style="width:${w(b.recency)}"></em>
      <em class="imp" style="width:${w(b.importance)}"></em>
      <em class="rel" style="width:${w(b.relevance)}"></em>
      <span>${b.score.toFixed(2)} = rec ${b.recency.toFixed(2)}
        + imp ${b.importance.toFixed(2)} + rel ${b.relevance.toFixed(2)}</span>
    </div></div>`;
}

export function renderFeed(el, conversations) {
  if (!conversations.length) {
    el.innerHTML = '<p class="hint">Nobody has spoken yet.</p>';
    return;
  }
  el.innerHTML = conversations.slice().reverse().map((c) => `
    <div class="conv">
      <header><span>${c.clock} &middot; ${esc(c.place)}</span>
        <span>${esc(c.topic)} ${c.sentiment >= 0 ? "+" : ""}${c.sentiment}</span></header>
      ${c.turns.map((t) => `<p><b style="color:${agentColour(t.speaker)}">
        ${esc(t.name.split(" ")[0])}:</b> ${esc(t.text)}</p>`).join("")}
      ${c.gossip ? `<p class="rumour">&rarr; passed on a rumour
        (distortion ${c.gossip.distortion}${c.gossip.truth_value ? "" : ", now false"})</p>` : ""}
    </div>`).join("");
}

export function renderCost(el, s) {
  const b = s.budget;
  const tiers = Object.entries(s.decisions_by_tier);
  const total = tiers.reduce((n, [, v]) => n + v, 0) || 1;
  const llmRows = Object.keys(b.limits).map((k) => `
    <tr><td>${k}</td><td>${b.calls[k] || 0}</td>
      <td>${b.used_today[k] || 0}/${b.limits[k]}</td>
      <td>${b.degraded[k] || 0}</td></tr>`).join("");

  el.innerHTML = `
    <h3>Where decisions are made</h3>
    <table class="cost"><tr><th>tier</th><th>count</th><th>share</th></tr>
      ${tiers.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td>
        <td>${pct(v / total)}</td></tr>`).join("")}
    </table>
    <p class="note">Only the <b>llm</b> tier reaches a model. Everything else is
      Tier 0 reflex, the daily plan, or a Tier 1 policy-cache hit.</p>

    <h3>Model calls</h3>
    <table class="cost">
      <tr><th>call type</th><th>total</th><th>today</th><th>degraded</th></tr>
      ${llmRows}
      <tr><td><b>all</b></td><td><b>${b.total_calls}</b></td><td></td><td></td></tr>
    </table>
    <p class="note">&ldquo;degraded&rdquo; counts calls that hit the daily ceiling
      and fell through to the template backend instead of failing.</p>

    <h3>Cost</h3>
    <dl class="kv">
      <dt>model</dt><dd>${esc(b.model)}</dd>
      <dt>total</dt><dd>$${b.total_usd.toFixed(6)}</dd>
      <dt>per sim-day</dt><dd>$${b.usd_per_sim_day.toFixed(6)}</dd>
      <dt>fresh in</dt><dd>${b.tokens.fresh_in.toLocaleString()} tok</dd>
      <dt>cached in</dt><dd>${b.tokens.cached_in.toLocaleString()} tok</dd>
      <dt>out</dt><dd>${b.tokens.out.toLocaleString()} tok</dd>
    </dl>
    <p class="note">The mock backend is free, so this reads $0. Token counts are
      real estimates of the prompts that were built, so switching
      <code>cognition.backend</code> to Claude prices this run without guessing.</p>

    <h3>Policy cache</h3>
    <dl class="kv">
      <dt>entries</dt><dd>${s.policy_cache.entries}</dd>
      <dt>hit rate</dt><dd>${pct(s.policy_cache.hit_rate)}</dd>
      <dt>hits/misses</dt><dd>${s.policy_cache.hits}/${s.policy_cache.misses}</dd>
    </dl>

    <h3>Memory</h3>
    <dl class="kv">
      <dt>on disk</dt><dd>${s.memory.on_disk}</dd>
      <dt>in RAM</dt><dd>${s.memory.in_ram}</dd>
      <dt>evicted</dt><dd>${s.memory.evicted}</dd>
      <dt>retrievals</dt><dd>${s.memory.retrievals}</dd>
    </dl>

    <h3>Integrity</h3>
    <dl class="kv">
      <dt>schema rejects</dt><dd>${s.validator.total}</dd>
      <dt>money imbalance</dt><dd>${s.economy.imbalance}</dd>
      <dt>ticks logged</dt><dd>${s.ticks_logged}</dd>
      <dt>run digest</dt><dd style="font-size:10px">${esc(s.digest)}</dd>
    </dl>
    <p class="note">The digest is a running hash of the whole tick log. Two runs
      from the same seed produce the same digest - that is the replay guarantee.</p>
  `;
}
