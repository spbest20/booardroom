"""Parasail: reads the raw stream into facts, then streams the UI manifest.

Both calls send a JSON schema in response_format so decoding is constrained
on the server. The compose call streams: reasoning tokens become "whispers"
in the séance panel and each finished component is validated and pushed to
the browser before the next one is written.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

from openai import APIStatusError, AsyncOpenAI
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .models import Component, IncidentFacts, Manifest, RealityCheck

PARASAIL_URL = "https://api.parasail.io/v1"
_component = TypeAdapter(Component)

Emit = Callable[[dict], Awaitable[None]]


def client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=PARASAIL_URL, api_key=settings.parasail_api_key, max_retries=0, timeout=45)


def _schema(model: type, name: str) -> dict:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": model.model_json_schema(), "strict": False}}


def _transient(e: Exception) -> bool:
    return (isinstance(e, APIStatusError) and e.status_code in (429, 500, 502, 503, 504)) or "overloaded" in str(
        e
    ).lower()


async def _with_fallback(settings: Settings, model: str, call):
    """Shared engines get overloaded at the event: retry, then switch models."""
    for attempt, m in enumerate([model, model, settings.fallback_model, settings.fallback_model]):
        try:
            return await call(m)
        except Exception as e:  # noqa: BLE001
            if not _transient(e) or attempt == 3:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))


EXTRACT_PROMPT = """You read raw incident logs from the AWS Builder Loft (525 Market St) during a paranormal outbreak drill.
Extract the facts. Use only these sector ids: entrance, main_stage, catering_coffee_bar, workshop, lounge, network_closet, green_room.
Map places to the closest sector (a coffee bar or catering area is catering_coffee_bar, a server room is network_closet).
Fog machines, party effects, crowds and pranks are false_alarm with severity low.
If previous facts are given, the new log is an UPDATE: carry forward anything it does not change."""


COMPOSE_PROMPT = """You are the layout engine of a Spooky Tactical Command Station. You do not write prose for a human to read:
you choose which interface components an operator needs, in the order they need them, and fill their props from the facts.

Component catalog (props in brackets):
- ThreatBanner [headline, entity, severity] - what is happening, in one punchy line
- EMFRadar [current_value, baseline_max, trend, status, refresh_rate_ms] - live EMF sweep; faster refresh when danger
- Thermometer [temp_c, baseline_min_c, status] - cold spots
- Floorplan [highlight_sector, ghost_sector, isolated_zones, civilians[{sector,count,status}]] - where it is and who is near it
- CivilianTracker [pinned, location, status, extraction_note] - people at risk and how to get them out
- NetworkNodes [nodes_affected, total_nodes, note] - only when the network is affected
- CounterMeasureSelector [target_entity, options[{name,why}], recommended] - names MUST be from the retrieved lore list
- RealityCheck [verdict, claims[{text,url}]] - mundane explanations from the web; verdict = one sentence based on the field researcher's finding; urls MUST be from the evidence list
- DispatchConsole [channel, draft, priority] - draft is ONE line: "<team> · [<sector>] · <action> · <why>"
- CalmStatus [message, explanation] - for false alarms: reassure and explain

Rules:
- 4 to 8 components, most urgent first. People in danger outrank instruments.
- A false alarm gets CalmStatus first, no ThreatBanner, and statuses "ok".
- Use each component at most once. Numbers come from the facts or the raw log, never invented.
- Always include RealityCheck. If reality_check is "pending", give it verdict "Checking the readings against the real world" and an empty claims list: the station fills it in when the Field Researcher reports. When anyone is pinned, include CivilianTracker and mark them on the Floorplan.
- Always end with DispatchConsole unless it is a false alarm with nothing to report.
- baseline_max for EMF is about 5 mG and baseline_min_c about 19 C unless the evidence says otherwise.
- If a previous layout is given this is an UPDATE: keep components that still matter, change their props, add what is new, drop what no longer applies.
- theme: blood-moon for critical, spectral-goth-dark for elevated, ecto-green for network hauntings, calm-dawn for false alarms."""


async def compose(
    settings: Settings,
    ai: AsyncOpenAI,
    *,
    raw: str,
    facts: IncidentFacts,
    lore: list[dict],
    evidence: list[dict],
    finding: str = "",
    reality_pending: bool = False,
    previous_layout: list[str],
    emit: Emit,
) -> Manifest:
    from .stream_parse import ComponentScanner

    context = {
        "team": settings.team or "team-??",
        "raw_log": raw,
        "facts": facts.model_dump(),
        "retrieved_lore": [{"name": e["name"], "counters": e["counters"], "risk": e["risk"]} for e in lore],
        "evidence": [{"url": e["url"], "title": e["title"], "text": e["text"]} for e in evidence],
        "field_researcher_finding": finding or None,
        "reality_check": "pending" if reality_pending else "evidence above",
        "previous_layout": previous_layout or None,
    }
    lore_names = {e["name"] for e in lore}
    urls = {e["url"] for e in evidence}

    async def call(model: str) -> Manifest:
        # A retry restarts the layout: the browser discards what this pass placed.
        await emit({"type": "compose_start", "model": model})
        stream = await ai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": COMPOSE_PROMPT}, {"role": "user", "content": json.dumps(context)}],
            response_format=_schema(Manifest, "ui_manifest"),
            temperature=0.4,
            stream=True,
        )
        scanner, placed, whisper, head_sent = ComponentScanner(), [], "", False
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            thought = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if thought:
                whisper += thought
                if len(whisper) > 60 or "\n" in whisper:
                    await emit({"type": "whisper", "text": whisper})
                    whisper = ""
            if not delta.content:
                continue
            for raw in scanner.feed(delta.content):
                comp = _checked(raw, lore_names, urls, placed, finding, reality_pending)
                if comp:
                    placed.append(comp)
                    await emit({"type": "component", "index": len(placed) - 1, "component": comp})
            if not head_sent and "headline" in (head := scanner.head()):
                head_sent = True
                await emit({"type": "head", **head})
        head = scanner.head()
        return Manifest.model_validate(
            {
                "theme": head.get("theme", "spectral-goth-dark"),
                "headline": head.get("headline", facts.summary),
                "ui_components_ordered": placed,
            }
        )

    return await _with_fallback(settings, settings.compose_model, call)


def _checked(
    raw: dict, lore_names: set[str], urls: set[str], placed: list[dict], finding: str = "", pending: bool = False
) -> dict | None:
    """Validate one streamed component; drop invented sources and counter-measures."""
    try:
        comp = _component.validate_python(raw).model_dump()
    except ValidationError:
        return None
    if any(p["component"] == comp["component"] for p in placed):
        return None
    if comp["component"] == "DispatchConsole":
        comp["channel"] = "#loft-incident"  # the venue's one escalation channel
    if comp["component"] == "NetworkNodes" and comp["total_nodes"] <= 0:
        comp["total_nodes"] = 12  # the loft's switch count when the model leaves it out
    if comp["component"] == "RealityCheck":
        comp["claims"] = [c for c in comp["claims"] if c["url"] in urls]
        if not comp["claims"]:
            return comp if pending else None  # pending: a slot the researcher's evidence fills later
        if (
            finding and len(comp["verdict"].split()) < 5
        ):  # a one-word verdict says nothing; the researcher's sentence does
            comp["verdict"] = finding
    if comp["component"] == "CounterMeasureSelector":
        comp["options"] = [o for o in comp["options"] if o["name"] in lore_names]
        if not comp["options"]:
            return None
        if comp["recommended"] not in {o["name"] for o in comp["options"]}:
            comp["recommended"] = comp["options"][0]["name"]
    return comp


def reality_panel(finding: str, evidence: list[dict]) -> dict | None:
    """The RealityCheck filled from the Field Researcher's own results: its finding, and excerpts it found."""
    if not evidence:
        return None
    claims = [{"text": _first_sentence(e["text"]) or e["title"], "url": e["url"]} for e in evidence[:3]]
    verdict = finding or "Everyday explanations for these readings, from the live web."
    return RealityCheck(component="RealityCheck", verdict=verdict, claims=claims).model_dump()


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.{20,220}?[.!?])(\s|$)", text)
    return m.group(1) if m else text[:200]
