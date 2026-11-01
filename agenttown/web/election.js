// The election panel: who is standing, how support moved, and the result.
// Also the rumour board, since a rumour that turns false is a campaign event.

import { SERIES, STATUS, barChart, lineChart, statTile } from "./charts.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Colour follows the candidate, fixed by their position in the field, so the
// hue does not move when the ranking does.
function colourOf(election, agentId) {
  const i = election.candidates.findIndex((c) => c.id === agentId);
  return SERIES[(i < 0 ? 0 : i) % SERIES.length];
}

export function renderElection(el, state) {
  const e = state.election;
  if (!e) {
    el.innerHTML = `<p class="hint">No election has been called.</p>
      <p class="note">Inject one from the <b>Inject</b> tab, or
      <code>POST /api/scenarios/election</code>. Opinions then move through
      conversation on their own: a warm political exchange pulls two people
      together, a sour one pushes them apart.</p>`;
    return;
  }

  el.innerHTML = "";
  const h = (html) => {
    const d = document.createElement("div");
    d.innerHTML = html;
    el.appendChild(d);
  };

  // --- headline state ------------------------------------------------
  const stats = document.createElement("div");
  stats.className = "stats";
  if (e.closed && e.result) {
    stats.append(
      statTile("turnout", `${Math.round(e.result.turnout * 100)}%`,
               `${e.result.votes_cast} of ${e.result.eligible}`),
      statTile("winner", e.result.winner_name
        ? esc(e.result.winner_name.split(" ")[0]) : "tie",
        e.result.winner_name ? "" : "dead heat"),
      statTile("meant to", e.intending, "did not all get there"),
    );
  } else {
    stats.append(
      statTile("days left", e.days_left, `voting on day ${e.election_day}`),
      statTile("standing", e.candidates.length),
      statTile(e.votes_cast ? "votes cast" : "intending",
               e.votes_cast || e.intending || 0),
    );
  }
  el.appendChild(stats);

  if (e.closed && e.result) {
    h(`<p class="sub">${esc(e.headline)}</p>`);
  }

  // --- the field -----------------------------------------------------
  h("<h3>Standing</h3>");
  for (const c of e.candidates) {
    const colour = colourOf(e, c.id);
    h(`<div class="cand" style="border-left-color:${colour}">
         <div>
           <h4 style="color:${colour}">${esc(c.name)}</h4>
           <p>${esc(c.platform)}</p>
           <span class="lean">position ${c.lean >= 0 ? "+" : ""}${c.lean}</span>
         </div>
       </div>`);
  }

  // --- support over time ---------------------------------------------
  const polls = e.polls || [];
  if (polls.length >= 2) {
    h("<h3>Support through the campaign</h3>");
    el.appendChild(lineChart({
      x: polls.map((p) => p.day),
      yLabel: "people who would vote for each candidate",
      series: e.candidates.map((c) => ({
        label: c.name,
        colour: colourOf(e, c.id),
        values: polls.map((p) => p.support[c.id] ?? 0),
      })),
    }));
    h(`<p class="note">Who each resident would vote for today, by whichever
       platform sits closest to their own position. Nobody is told what to
       think: this moves only because people talk to each other.</p>`);

    // polarisation is a different measure, so it gets its own chart - never
    // a second y-axis on the one above
    h("<h3>Polarisation</h3>");
    el.appendChild(lineChart({
      x: polls.map((p) => p.day),
      height: 110,
      yMax: 1,
      series: [{
        label: "polarisation", colour: SERIES[2],
        values: polls.map((p) => p.polarisation),
      }],
    }));
    h(`<p class="note">The standard deviation of opinion across the town, on a
       scale of 0 to 1. It widens when political conversations go badly, and is
       measured this way rather than as a range so that two hardliners cannot
       peg it at the ceiling.</p>`);
  }

  // --- the count -----------------------------------------------------
  if (e.closed && e.result) {
    h("<h3>The count</h3>");
    const tally = e.result.tally || {};
    el.appendChild(barChart({
      unit: " votes",
      rows: e.candidates.map((c) => ({
        label: c.name.split(" ")[0],
        value: tally[c.id] ?? 0,
        colour: colourOf(e, c.id),
      })),
    }));
    h(`<table class="data">
        <tr><th>candidate</th><th>votes</th><th>share</th></tr>
        ${e.candidates.map((c) => {
          const v = tally[c.id] ?? 0;
          const share = e.result.votes_cast
            ? Math.round((100 * v) / e.result.votes_cast) : 0;
          return `<tr><td>${esc(c.name)}</td><td>${v}</td><td>${share}%</td></tr>`;
        }).join("")}
        <tr><td>did not vote</td>
            <td>${e.result.eligible - e.result.votes_cast}</td><td></td></tr>
      </table>
      <p class="note">A table as well as the bars, so the result does not
      depend on reading colour.</p>`);
  }
}

export function renderRumours(el, state) {
  const g = state.gossip;
  const n = state.agents.length;
  if (!g || !g.items.length) {
    el.innerHTML = '<p class="hint">No rumours in circulation.</p>';
    return;
  }
  el.innerHTML = "";
  const intro = document.createElement("div");
  intro.innerHTML = `<p class="sub">${g.distinct} distinct rumour(s). Every
    retelling raises the distortion count and may flip a true thing into a
    false one. A rumour about a candidate that has turned false costs them
    support with whoever heard it.</p>`;
  el.appendChild(intro);

  el.appendChild(barChart({
    max: n,
    unit: ` of ${n}`,
    rows: g.items.map((it) => ({
      label: it.sentence.length > 34
        ? `${it.sentence.slice(0, 32)}...` : it.sentence,
      value: it.carriers,
      // state, not identity: a discredited rumour wears the status colour and
      // carries a written label, never colour alone
      colour: it.went_false ? STATUS.critical : SERIES[0],
      note: it.went_false ? "turned false" : "",
    })),
  }));

  const table = document.createElement("div");
  table.innerHTML = `<table class="data">
      <tr><th>rumour</th><th>knows</th><th>distortion</th><th>state</th></tr>
      ${g.items.map((it) => `<tr>
        <td>${esc(it.sentence)}</td>
        <td>${it.carriers}</td>
        <td>${it.max_distortion}</td>
        <td>${it.went_false ? "false" : "true"}</td></tr>`).join("")}
    </table>`;
  el.appendChild(table);
}
