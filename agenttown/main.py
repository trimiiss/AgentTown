"""FastAPI host: one WebSocket for state, a few REST endpoints for control.

The frontend is plain ES modules served as static files - no npm, no bundler,
no second dev server. On a 5.8 GB machine that matters more than ergonomics.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .sim.loop import Simulation

WEB = Path(__file__).parent / "web"

cfg = Config.load(Path(__file__).parent.parent / "config" / "sim.toml")
sim = Simulation(cfg)

app = FastAPI(title="AgentTown")
_clients: set[WebSocket] = set()
_state: dict = {"ms_per_tick": cfg.sim.real_ms_per_tick, "steps_requested": 0}


# ---------------------------------------------------------------- models
class EventIn(BaseModel):
    kind: str
    payload: dict = {}
    scope: str = "town"
    importance: float = 8.0


class ControlIn(BaseModel):
    action: str                 # pause | resume | step | speed | reset
    value: float | None = None


# ---------------------------------------------------------------- ticker
async def _broadcast() -> None:
    if not _clients:
        return
    message = json.dumps(sim.snapshot())
    for ws in list(_clients):
        try:
            await ws.send_text(message)
        except Exception:
            _clients.discard(ws)


async def _ticker() -> None:
    while True:
        stepped = False
        if not sim.paused:
            sim.step()
            stepped = True
        elif _state["steps_requested"] > 0:
            _state["steps_requested"] -= 1
            sim.step()
            stepped = True
        if stepped:
            await _broadcast()
        await asyncio.sleep(max(10, _state["ms_per_tick"]) / 1000)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_ticker())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        sim.close()


app.router.lifespan_context = lifespan


# ---------------------------------------------------------------- routes
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/town")
async def town() -> JSONResponse:
    """The static world. Sent once; it never changes during a run."""
    return JSONResponse({
        "width": sim.grid.width, "height": sim.grid.height,
        "terrain": sim.grid.terrain,
        "areas": [
            {"id": a.id, "name": a.name, "kind": a.kind, "x0": a.x0, "y0": a.y0,
             "x1": a.x1, "y1": a.y1, "entrance": list(a.entrance)}
            for a in sim.grid.areas.values()
        ],
        "objects": [
            {"id": o.id, "name": o.name, "x": o.x, "y": o.y, "area": o.area,
             "affordances": list(o.affordances)}
            for o in sim.grid.objects.values()
        ],
        "agents": [
            {"id": a.id, "name": a.name, "occupation": a.occupation}
            for a in (sim.agents[i] for i in sim.order)
        ],
        "ticks_per_day": cfg.sim.ticks_per_day,
        "seed": cfg.sim.seed,
    })


@app.get("/api/state")
async def state() -> JSONResponse:
    return JSONResponse(sim.snapshot())


@app.get("/api/agent/{agent_id}")
async def agent(agent_id: str) -> JSONResponse:
    detail = sim.detail(agent_id)
    if not detail:
        return JSONResponse({"error": "no such agent"}, status_code=404)
    return JSONResponse(detail)


@app.get("/api/llm")
async def llm() -> JSONResponse:
    return JSONResponse({"budget": sim.budget.stats(), "recent": sim.llm_log[-40:]})


@app.post("/api/events")
async def inject(ev: EventIn) -> JSONResponse:
    created = sim.inject(ev.kind, ev.payload, ev.scope, ev.importance)
    return JSONResponse(created.as_dict())


@app.get("/api/scenarios")
async def scenarios() -> JSONResponse:
    folder = cfg.root / "config" / "scenarios"
    out = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"name": path.stem, "title": data.get("title", path.stem),
                    "description": data.get("description", ""),
                    "events": len(data.get("events", []))})
    return JSONResponse(out)


@app.post("/api/scenarios/{name}")
async def run_scenario(name: str) -> JSONResponse:
    path = cfg.root / "config" / "scenarios" / f"{name}.json"
    if not path.exists():
        return JSONResponse({"error": "no such scenario"}, status_code=404)
    data = json.loads(path.read_text(encoding="utf-8"))
    created = [
        sim.inject(e["kind"], e.get("payload", {}), e.get("scope", "town"),
                   float(e.get("importance", 8.0))).as_dict()
        for e in data.get("events", [])
    ]
    return JSONResponse({"injected": created})


@app.post("/api/control")
async def control(c: ControlIn) -> JSONResponse:
    if c.action == "pause":
        sim.paused = True
    elif c.action == "resume":
        sim.paused = False
    elif c.action == "step":
        _state["steps_requested"] += int(c.value or 1)
    elif c.action == "speed" and c.value:
        _state["ms_per_tick"] = int(c.value)
    return JSONResponse({"paused": sim.paused,
                         "ms_per_tick": _state["ms_per_tick"],
                         "queued_steps": _state["steps_requested"]})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    try:
        await ws.send_text(json.dumps(sim.snapshot()))
        while True:
            await ws.receive_text()      # client keepalive only
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


app.mount("/static", StaticFiles(directory=WEB), name="static")
