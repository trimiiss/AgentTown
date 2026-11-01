// Small hand-written SVG charts for the dashboard panels.
//
// Palette note: the three categorical slots and the status colours below are
// the validated dark-mode steps, checked against this panel surface (#1b1e24)
// for the lightness band, chroma floor, CVD separation, normal-vision floor
// and 3:1 contrast. Do not substitute hues without re-running that check.
//
// Colour follows the entity, never its rank: a candidate keeps their hue when
// the ordering changes, so the losing bar does not steal the winner's colour.

export const SERIES = ["#3987e5", "#d95926", "#199e70"];
export const STATUS = { critical: "#d03b3b", good: "#0ca30c" };
const INK = "var(--ink)";
const MUTED = "var(--muted)";
const GRID = "rgba(230,232,236,0.09)";

const SVGNS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}, text = null) {
  const node = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== null) node.textContent = text;
  return node;
}

function tooltip() {
  const box = document.createElement("div");
  box.className = "chart-tip";
  box.hidden = true;
  return box;
}

/**
 * Change over time, one line per series. Legend always present for >= 2
 * series; the last point of each line is directly labelled, so identity is
 * never carried by colour alone.
 */
export function lineChart({ series, x, yLabel = "", height = 150, yMax = null }) {
  const wrap = document.createElement("div");
  wrap.className = "chart";
  if (!series.length || x.length < 2) {
    wrap.innerHTML = '<p class="hint">Not enough history yet.</p>';
    return wrap;
  }

  const W = 380;
  const H = height;
  const pad = { l: 28, r: 54, t: 10, b: 20 };
  const top = yMax ?? Math.max(1, ...series.flatMap((s) => s.values));
  const px = (i) => pad.l + (i * (W - pad.l - pad.r)) / (x.length - 1);
  const py = (v) => H - pad.b - (v / top) * (H - pad.t - pad.b);

  const svg = el("svg", {
    viewBox: `0 0 ${W} ${H}`, width: "100%", height: H,
    role: "img", "aria-label": yLabel || "time series",
  });

  // recessive grid and axis ticks
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = (top * i) / ticks;
    svg.appendChild(el("line", {
      x1: pad.l, x2: W - pad.r, y1: py(v), y2: py(v), stroke: GRID,
      "stroke-width": 1,
    }));
    svg.appendChild(el("text", {
      x: pad.l - 5, y: py(v) + 3, fill: MUTED, "font-size": 8,
      "text-anchor": "end",
    }, String(Math.round(v))));
  }
  for (let i = 0; i < x.length; i += Math.ceil(x.length / 6)) {
    svg.appendChild(el("text", {
      x: px(i), y: H - 6, fill: MUTED, "font-size": 8, "text-anchor": "middle",
    }, String(x[i])));
  }

  series.forEach((s, n) => {
    const colour = s.colour || SERIES[n % SERIES.length];
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join("");
    svg.appendChild(el("path", {
      d, fill: "none", stroke: colour, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
    // few enough points to mark them individually
    if (x.length <= 14) {
      s.values.forEach((v, i) => {
        svg.appendChild(el("circle", {
          cx: px(i), cy: py(v), r: 3, fill: colour,
          stroke: "var(--panel)", "stroke-width": 2,   // 2px surface ring
        }));
      });
    }
    const last = s.values.length - 1;
    svg.appendChild(el("text", {
      x: px(last) + 7, y: py(s.values[last]) + 3, fill: colour,
      "font-size": 9, "font-weight": 600,
    }, s.label.split(" ")[0]));
  });

  // hover crosshair + tooltip
  const crosshair = el("line", {
    y1: pad.t, y2: H - pad.b, stroke: "var(--muted)", "stroke-width": 1,
    "stroke-dasharray": "2 2", opacity: 0,
  });
  svg.appendChild(crosshair);
  const tip = tooltip();

  svg.addEventListener("mousemove", (ev) => {
    const box = svg.getBoundingClientRect();
    const rel = ((ev.clientX - box.left) / box.width) * W;
    let i = Math.round(((rel - pad.l) / (W - pad.l - pad.r)) * (x.length - 1));
    i = Math.max(0, Math.min(x.length - 1, i));
    crosshair.setAttribute("x1", px(i));
    crosshair.setAttribute("x2", px(i));
    crosshair.setAttribute("opacity", 1);
    tip.hidden = false;
    tip.innerHTML =
      `<b>day ${x[i]}</b>` +
      series.map((s, n) => {
        const colour = s.colour || SERIES[n % SERIES.length];
        return `<span><i style="background:${colour}"></i>${s.label}: ` +
               `<b>${s.values[i]}</b></span>`;
      }).join("");
    tip.style.left = `${Math.min(ev.offsetX + 12, box.width - 130)}px`;
    tip.style.top = `${ev.offsetY + 8}px`;
  });
  svg.addEventListener("mouseleave", () => {
    crosshair.setAttribute("opacity", 0);
    tip.hidden = true;
  });

  wrap.appendChild(svg);
  wrap.appendChild(tip);
  if (series.length >= 2) wrap.appendChild(legend(series));
  return wrap;
}

function legend(series) {
  const box = document.createElement("div");
  box.className = "chart-legend";
  box.innerHTML = series.map((s, n) => {
    const colour = s.colour || SERIES[n % SERIES.length];
    return `<span><i style="background:${colour}"></i>${s.label}</span>`;
  }).join("");
  return box;
}

/**
 * Magnitude across a few named things. Horizontal, because the labels are
 * words; 4px rounded data-end anchored to the baseline; values labelled
 * directly rather than on an axis.
 */
export function barChart({ rows, max = null, unit = "" }) {
  const wrap = document.createElement("div");
  wrap.className = "chart";
  if (!rows.length) {
    wrap.innerHTML = '<p class="hint">Nothing to show yet.</p>';
    return wrap;
  }
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  wrap.innerHTML = rows.map((r, n) => {
    const colour = r.colour || SERIES[n % SERIES.length];
    const pct = Math.max(1.5, (r.value / top) * 100);
    return `<div class="bar-row" title="${r.label}: ${r.value}${unit}">
      <span class="bar-label">${r.label}</span>
      <span class="bar-track">
        <span class="bar-fill" style="width:${pct}%;background:${colour}"></span>
      </span>
      <span class="bar-value">${r.value}${unit}${
        r.note ? ` <em>${r.note}</em>` : ""}</span>
    </div>`;
  }).join("");
  return wrap;
}

/** A single headline figure. Not every number deserves a plot. */
export function statTile(label, value, sub = "") {
  const box = document.createElement("div");
  box.className = "stat";
  box.innerHTML = `<b>${value}</b><span>${label}</span>` +
    (sub ? `<i>${sub}</i>` : "");
  return box;
}
