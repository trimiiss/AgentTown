// Wiring: fetch the static town once, then take state over a WebSocket.

import { TownRenderer } from "./render.js";
import { renderAgent, renderCost, renderFeed } from "./inspector.js";
import { renderElection, renderRumours } from "./election.js";

const $ = (s) => document.querySelector(s);

let town = null;
let renderer = null;
let latest = null;
let selected = null;
let activeTab = "agent";
let detailInFlight = false;

async function boot() {
  town = await (await fetch("/api/town")).json();
  renderer = new TownRenderer($("#map"), town);
  $("#legend").innerHTML = renderer.legendHtml();

  const list = $("#scope-list");
  list.innerHTML = ["town", ...town.areas.map((a) => a.id),
                    ...town.agents.map((a) => a.id)]
    .map((v) => `<option value="${v}">`).join("");

  wireControls();
  await loadScenarios();
  connect();
}

// ------------------------------------------------------------- socket
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  const keepalive = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 15000);

  ws.onmessage = (e) => apply(JSON.parse(e.data));
  ws.onclose = () => {
    clearInterval(keepalive);
    $("#clock").textContent = "--:--";
    setTimeout(connect, 1500);
  };
}

function apply(s) {
  latest = s;
  renderer.selected = selected;
  renderer.draw(s.agents);

  $("#clock").textContent = s.clock;
  $("#day").textContent = `day ${s.day} · tick ${s.tick}`;
  $("#btn-pause").textContent = s.paused ? "Resume" : "Pause";

  const tiers = Object.entries(s.decisions_by_tier)
    .map(([k, v]) => `${k} ${v}`).join("  ");
  $("#meters").innerHTML = `
    <span>bread <b>${(s.economy.prices.bread ?? 0).toFixed(2)}</b></span>
    <span>money <b>${s.economy.total_money.toFixed(0)}</b></span>
    <span>llm calls <b>${s.budget.total_calls}</b></span>
    <span>cost <b>$${s.budget.total_usd.toFixed(5)}</b></span>
    <span>cache <b>${Math.round(s.policy_cache.hit_rate * 100)}%</b></span>
    ${s.election ? `<span>${s.election.closed
        ? `election: <b>${s.election.result && s.election.result.winner_name
            ? s.election.result.winner_name.split(" ")[0] : "tied"}</b>`
        : `vote in <b>${s.election.days_left}d</b>`}</span>` : ""}
    <span class="muted">${tiers}</span>`;

  if (activeTab === "feed") renderFeed($("#feed"), s.conversations);
  if (activeTab === "gossip") renderRumours($("#gossip"), s);
  if (activeTab === "election") renderElection($("#election"), s);
  if (activeTab === "cost") renderCost($("#cost"), s);
  if (activeTab === "agent" && selected) refreshDetail();
}

async function refreshDetail() {
  if (!selected || detailInFlight) return;
  detailInFlight = true;
  try {
    const d = await (await fetch(`/api/agent/${selected}`)).json();
    if (activeTab === "agent") renderAgent($("#tab-agent"), d, town);
  } finally {
    detailInFlight = false;
  }
}

// ------------------------------------------------------------ controls
function wireControls() {
  const canvas = $("#map");
  canvas.addEventListener("click", (e) => {
    const id = renderer.agentAt(e.clientX, e.clientY);
    if (!id) return;
    selected = id;
    renderer.selected = id;
    switchTab("agent");
    refreshDetail();
  });
  canvas.addEventListener("mousemove", (e) => {
    const id = renderer.agentAt(e.clientX, e.clientY);
    if (id !== renderer.hover) {
      renderer.hover = id;
      canvas.style.cursor = id ? "pointer" : "crosshair";
      if (latest) renderer.draw(latest.agents);
    }
  });

  $("#btn-pause").addEventListener("click", () =>
    post("/api/control", { action: latest && latest.paused ? "resume" : "pause" }));
  $("#btn-step").addEventListener("click", () =>
    post("/api/control", { action: "step", value: 1 }));
  $("#speed").addEventListener("change", (e) =>
    post("/api/control", { action: "speed", value: Number(e.target.value) }));

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (e.code === "Space") {
      e.preventDefault();
      $("#btn-pause").click();
    } else if (e.key === ".") {
      $("#btn-step").click();
    }
  });

  for (const b of document.querySelectorAll(".tabs button")) {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  }

  $("#custom-event").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    let payload;
    try {
      payload = JSON.parse(f.get("payload") || "{}");
    } catch (err) {
      $("#inject-result").textContent = `payload is not valid JSON: ${err.message}`;
      return;
    }
    const ev = await post("/api/events", {
      kind: f.get("kind"), payload, scope: f.get("scope") || "town",
    });
    $("#inject-result").textContent = `injected: ${ev.text}`;
  });
}

function switchTab(name) {
  activeTab = name;
  for (const b of document.querySelectorAll(".tabs button")) {
    b.classList.toggle("active", b.dataset.tab === name);
  }
  for (const d of document.querySelectorAll(".tab")) {
    d.classList.toggle("active", d.id === `tab-${name}`);
  }
  if (!latest) return;
  if (name === "feed") renderFeed($("#feed"), latest.conversations);
  if (name === "gossip") renderRumours($("#gossip"), latest);
  if (name === "election") renderElection($("#election"), latest);
  if (name === "cost") renderCost($("#cost"), latest);
  if (name === "agent") refreshDetail();
}

async function loadScenarios() {
  const list = await (await fetch("/api/scenarios")).json();
  $("#scenarios").innerHTML = list.map((s) => `
    <div class="scn">
      <h4>${s.title}</h4>
      <p>${s.description}</p>
      <button data-scenario="${s.name}">Inject ${s.events} event(s)</button>
    </div>`).join("");
  for (const b of document.querySelectorAll("[data-scenario]")) {
    b.addEventListener("click", async () => {
      const r = await post(`/api/scenarios/${b.dataset.scenario}`, {});
      $("#inject-result").textContent =
        r.injected.map((e) => e.text).join(" / ");
    });
  }
}

async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

boot();
