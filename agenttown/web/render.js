// Canvas rendering. Terrain is static for a whole run, so it is drawn once to
// an offscreen buffer and blitted each frame; only agents and bubbles redraw.

export const TILE = 16;

const AREA_FILL = {
  home: "#262033",
  bakery: "#3a2d20",
  cafe: "#33281c",
  shop: "#1f2b2b",
  clinic: "#1c2b30",
  school: "#1f2733",
  mosque: "#20302a",
  church: "#2a2230",
  municipality: "#2b2a22",
  market: "#2d2a1e",
  park: "#1c2a1f",
  street: "#191c21",
};

const LEGEND_LABEL = {
  home: "homes", bakery: "furra", cafe: "kafiteria", shop: "dyqani",
  clinic: "ambulanca", school: "shkolla", mosque: "xhamia", church: "kisha",
  municipality: "komuna", market: "pazari", park: "parku", street: "çarshia",
};

// Stable per-agent colour from the id, so it never shifts between runs.
export function agentColour(id) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 58% 62%)`;
}

export function initials(name) {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2);
}

export class TownRenderer {
  constructor(canvas, town) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.town = town;
    this.hover = null;
    this.selected = null;
    this.agentMeta = new Map(town.agents.map((a) => [a.id, a]));
    this.lastAgents = [];

    canvas.width = town.width * TILE;
    canvas.height = town.height * TILE;
    this.base = document.createElement("canvas");
    this.base.width = canvas.width;
    this.base.height = canvas.height;
    this._drawTerrain();
  }

  // ----------------------------------------------------------- terrain
  _drawTerrain() {
    const g = this.base.getContext("2d");
    const { width, height, terrain, areas, objects } = this.town;

    g.fillStyle = "#0f1115";
    g.fillRect(0, 0, this.base.width, this.base.height);

    // area floors first, buildings over the street band
    const ordered = [...areas].sort(
      (a, b) => (a.kind === "street" ? 0 : 1) - (b.kind === "street" ? 0 : 1),
    );
    for (const a of ordered) {
      g.fillStyle = AREA_FILL[a.kind] || "#1a1d22";
      g.fillRect(a.x0 * TILE, a.y0 * TILE,
                 (a.x1 - a.x0 + 1) * TILE, (a.y1 - a.y0 + 1) * TILE);
    }

    // walls and grass on top of the floors
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const c = terrain[y][x];
        if (c === "#") {
          g.fillStyle = "#3b4150";
          g.fillRect(x * TILE, y * TILE, TILE, TILE);
          g.fillStyle = "#454c5d";
          g.fillRect(x * TILE, y * TILE, TILE, 2);
        } else if (c === ",") {
          g.fillStyle = "#1e2d22";
          g.fillRect(x * TILE, y * TILE, TILE, TILE);
          g.fillStyle = "#273a2b";
          for (let i = 0; i < 3; i++) {
            const px = x * TILE + ((x * 7 + i * 5) % TILE);
            const py = y * TILE + ((y * 11 + i * 3) % TILE);
            g.fillRect(px, py, 2, 2);
          }
        }
      }
    }

    // objects as small marks, so the furnishing of a room is visible
    for (const o of objects) {
      g.fillStyle = "rgba(216,166,87,0.45)";
      g.fillRect(o.x * TILE + 4, o.y * TILE + 4, TILE - 8, TILE - 8);
      g.strokeStyle = "rgba(216,166,87,0.7)";
      g.lineWidth = 1;
      g.strokeRect(o.x * TILE + 3.5, o.y * TILE + 3.5, TILE - 7, TILE - 7);
    }

    // area labels, skipping the street band
    g.font = "600 9px system-ui, sans-serif";
    g.textAlign = "center";
    for (const a of areas) {
      if (a.kind === "street") continue;
      const cx = ((a.x0 + a.x1 + 1) / 2) * TILE;
      const label = a.name.toUpperCase();
      g.fillStyle = "rgba(0,0,0,0.45)";
      const w = g.measureText(label).width;
      g.fillRect(cx - w / 2 - 3, a.y0 * TILE + 2, w + 6, 11);
      g.fillStyle = "rgba(230,232,236,0.6)";
      g.fillText(label, cx, a.y0 * TILE + 10);
    }
  }

  legendHtml() {
    const kinds = [...new Set(this.town.areas.map((a) => a.kind))];
    return kinds
      .map((k) => `<span><i style="background:${AREA_FILL[k] || "#1a1d22"};
                   border:1px solid #3b4150"></i>${LEGEND_LABEL[k] || k}</span>`)
      .join("");
  }

  // ------------------------------------------------------------ agents
  draw(agents) {
    this.lastAgents = agents;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.drawImage(this.base, 0, 0);

    for (const a of agents) {
      const cx = a.x * TILE + TILE / 2;
      const cy = a.y * TILE + TILE / 2;
      const colour = agentColour(a.id);
      const isSel = a.id === this.selected;
      const isHov = a.id === this.hover;

      if (isSel) {
        ctx.beginPath();
        ctx.arc(cx, cy, TILE * 0.78, 0, Math.PI * 2);
        ctx.strokeStyle = "#d8a657";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(cx, cy + 1, TILE * 0.42, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, TILE * 0.42, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.fill();
      ctx.strokeStyle = a.walking ? "#e6e8ec" : "rgba(0,0,0,0.5)";
      ctx.lineWidth = a.walking ? 1.5 : 1;
      ctx.stroke();

      ctx.font = "600 8px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillStyle = "rgba(0,0,0,0.8)";
      const meta = this.agentMeta.get(a.id);
      ctx.fillText(initials(meta ? meta.name : a.id), cx, cy + 3);

      if (isSel || isHov) {
        const label = (meta ? meta.name : a.id);
        ctx.font = "9px system-ui, sans-serif";
        const w = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(0,0,0,0.7)";
        ctx.fillRect(cx - w / 2 - 3, cy + TILE * 0.55, w + 6, 12);
        ctx.fillStyle = "#e6e8ec";
        ctx.fillText(label, cx, cy + TILE * 0.55 + 9);
      }
    }

    // speech bubbles last, so they sit above everybody
    for (const a of agents) {
      if (!a.speech) continue;
      this._bubble(a.x * TILE + TILE / 2, a.y * TILE - 4, a.speech,
                   agentColour(a.id));
    }
  }

  _bubble(x, y, text, colour) {
    const ctx = this.ctx;
    ctx.font = "10px system-ui, sans-serif";
    const words = text.split(" ");
    const lines = [];
    let line = "";
    for (const w of words) {
      const next = line ? `${line} ${w}` : w;
      if (ctx.measureText(next).width > 150 && line) {
        lines.push(line);
        line = w;
      } else {
        line = next;
      }
    }
    if (line) lines.push(line);
    const trimmed = lines.slice(0, 3);

    const w = Math.max(...trimmed.map((l) => ctx.measureText(l).width)) + 12;
    const h = trimmed.length * 12 + 8;
    let bx = x - w / 2;
    bx = Math.max(2, Math.min(this.canvas.width - w - 2, bx));
    const by = Math.max(2, y - h);

    ctx.fillStyle = "rgba(20,22,26,0.94)";
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(bx, by, w, h, 5);
    ctx.fill();
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(x - 4, by + h);
    ctx.lineTo(x, by + h + 5);
    ctx.lineTo(x + 4, by + h);
    ctx.fillStyle = "rgba(20,22,26,0.94)";
    ctx.fill();

    ctx.fillStyle = "#e6e8ec";
    ctx.textAlign = "left";
    trimmed.forEach((l, i) => ctx.fillText(l, bx + 6, by + 14 + i * 12));
  }

  // ------------------------------------------------------------- input
  agentAt(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const scale = this.canvas.width / r.width;
    const px = (clientX - r.left) * scale;
    const py = (clientY - r.top) * scale;
    let best = null;
    let bestD = TILE * 1.4;
    for (const a of this.lastAgents) {
      const dx = a.x * TILE + TILE / 2 - px;
      const dy = a.y * TILE + TILE / 2 - py;
      const d = Math.hypot(dx, dy);
      if (d < bestD) {
        best = a.id;
        bestD = d;
      }
    }
    return best;
  }
}
