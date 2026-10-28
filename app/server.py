"""FastAPI server: serves the station and runs incidents over a WebSocket.

Browser -> server:  {"type": "incident", "text": "..."} | {"type": "dispatch", "content": "..."} | {"type": "reset"}
Server -> browser:  stage, facts, research, evidence, lore, compose_start, whisper, head,
                    component, manifest (partial while the reality check is pending),
                    dispatch, warning, error
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAI

load_dotenv()

from .agents import StationAgents  # noqa: E402 - settings read the loaded .env
from .config import Settings  # noqa: E402
from .dispatch import dispatch  # noqa: E402
from .grounding import YouSearch  # noqa: E402
from .lore import LoreIndex  # noqa: E402
from .models import IncidentFacts  # noqa: E402
from .parasail import PARASAIL_URL, client  # noqa: E402
from .pipeline import IncidentFlow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"

settings = Settings()
ai = client(settings)
search = YouSearch(settings.ydc_api_key)
agents = StationAgents(settings, search)
lore = LoreIndex(OpenAI(base_url=PARASAIL_URL, api_key=settings.parasail_api_key, max_retries=0), settings.embed_model)


async def _quiet(_event: dict) -> None:
    pass


def _flow(raw: str, previous: IncidentFacts | None, layout: list[str], emit) -> IncidentFlow:
    return IncidentFlow(
        settings=settings,
        ai=ai,
        agents=agents,
        lore=lore,
        raw=raw,
        previous=previous,
        previous_layout=layout,
        emit=emit,
    )


async def _warm_up() -> None:
    """Pay one-time costs before the first report: CrewAI's first Flow takes ~5 s to build,
    and the lore library has to be embedded once."""
    await asyncio.to_thread(_flow, "", None, [], _quiet)
    await asyncio.to_thread(lore.search, "warm up")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warm = asyncio.create_task(_warm_up())
    yield
    warm.cancel()


app = FastAPI(title="Boo-ard Room", lifespan=lifespan)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/snapshot.js")
def snapshot() -> FileResponse:
    return FileResponse(ROOT / "web" / "snapshot.js", media_type="text/javascript")


@app.get("/api/status")
def status() -> dict:
    return {
        "dispatch_mode": settings.dispatch_mode,
        "team": settings.team or "team-??",
        "compose_model": settings.compose_model,
        "dispatch_via": "webhook" if settings.discord_webhook_url else "none",
    }


@app.get("/api/night")
def night() -> JSONResponse:
    return JSONResponse(json.loads((ROOT / "data" / "night.json").read_text()))


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    send_lock, work = asyncio.Lock(), asyncio.Lock()  # one incident at a time per station
    previous: IncidentFacts | None = None
    layout: list[str] = []
    tasks: set[asyncio.Task] = set()

    async def emit(event: dict) -> None:
        async with send_lock:
            await socket.send_json(event)

    async def run_incident(text: str) -> None:
        nonlocal previous, layout
        async with work:
            try:
                flow = _flow(text, previous, layout, emit)
                await flow.kickoff_async()
                previous = flow.state.facts
                if flow.state.manifest:
                    layout = [c.component for c in flow.state.manifest.ui_components_ordered]
                    OUT.mkdir(exist_ok=True)
                    (OUT / "latest.json").write_text(flow.state.manifest.model_dump_json(indent=2))
            except Exception as e:  # noqa: BLE001 - surface every failure in the UI
                await emit({"type": "error", "text": f"{type(e).__name__}: {e}"})

    async def send_dispatch(content: str) -> None:
        await emit({"type": "dispatch", **await asyncio.to_thread(dispatch, settings, content)})

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    try:
        while True:
            msg = await socket.receive_json()
            kind = msg.get("type")
            if kind == "incident" and msg.get("text", "").strip():
                spawn(run_incident(msg["text"].strip()))
            elif kind == "dispatch" and msg.get("content", "").strip():
                spawn(send_dispatch(msg["content"]))
            elif kind == "reset":
                previous, layout = None, []
    except WebSocketDisconnect:
        for task in tasks:
            task.cancel()
