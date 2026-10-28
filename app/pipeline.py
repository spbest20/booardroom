"""One incident through the station, as a CrewAI Flow.

read        - the Intake Analyst agent extracts facts from the raw log (schema-locked)
route       - router on incident class: a false alarm takes the calm path
investigate / reassure
            - in parallel: lore retrieval (Parasail embeddings) and the
              Field Researcher agent's You.com reality check of the readings
compose     - Parasail streams the manifest; components reach the browser
              one by one as they are written. If the web research is still
              running, the model reserves the RealityCheck slot and the
              researcher's results fill it in when they land
"""

from __future__ import annotations

import asyncio

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import BaseModel

from .agents import StationAgents
from .grounding import reality_query
from .lore import LoreIndex
from .models import IncidentFacts, Manifest
from .parasail import Emit, compose, reality_panel


class IncidentState(BaseModel):
    facts: IncidentFacts | None = None
    lore: list[dict] = []
    evidence: list[dict] = []
    finding: str = ""
    manifest: Manifest | None = None


class IncidentFlow(Flow[IncidentState]):
    def __init__(
        self,
        *,
        settings,
        ai,
        agents: StationAgents,
        lore: LoreIndex,
        raw: str,
        previous: IncidentFacts | None,
        previous_layout: list[str],
        emit: Emit,
    ):
        super().__init__()
        self.settings, self.ai, self.agents, self.lore_index = settings, ai, agents, lore
        self.raw, self.previous, self.previous_layout, self.emit = raw, previous, previous_layout, emit

    async def _stage(self, stage: str, detail: str = "") -> None:
        await self.emit({"type": "stage", "stage": stage, "detail": detail})

    @start()
    async def read(self):
        await self._stage("read", "Intake Analyst is reading · Field Researcher is searching")
        # The researcher works from the raw report, so it starts now instead of after the read.
        self._research = asyncio.create_task(self.agents.research(self.raw, self.previous))
        try:
            self.state.facts = await self.agents.intake(self.raw, self.previous)
        except BaseException:
            self._research.cancel()
            raise
        await self.emit({"type": "facts", "facts": self.state.facts.model_dump()})

    @router(read)
    async def route(self):
        f = self.state.facts
        await self._stage("route", f"{f.incident_class.replace('_', ' ')} · {f.severity}")
        return "calm" if f.incident_class == "false_alarm" else "haunting"

    async def _gather(self, lore_query: str) -> None:
        await self._stage("ground", "lore retrieval · Field Researcher still searching")
        lore, method = await asyncio.to_thread(self.lore_index.search, lore_query)
        self.state.lore = lore
        await self.emit({"type": "lore", "lore": [e["name"] for e in lore], "method": method})

    async def _reality(self) -> tuple[list[dict], str]:
        """The Field Researcher's results, or one fixed search if it stalled or found nothing."""
        try:
            evidence, brief = await self._research
            if not evidence:
                evidence = await asyncio.to_thread(self.agents.search.search, reality_query(self.state.facts))
        except Exception as e:  # noqa: BLE001 - grounding failure drops the panel, not the station
            await self.emit({"type": "warning", "text": f"You.com search failed: {e}"})
            return [], ""
        await self.emit(
            {
                "type": "research",
                "queries": brief.queries if brief else [],
                "finding": brief.finding if brief else "",
                "by": "agent" if brief else "fixed query",
            }
        )
        found = [e.as_dict() for e in evidence]
        await self.emit({"type": "evidence", "evidence": found})
        return found, brief.finding if brief else ""

    def _fill_reality(self, manifest: Manifest) -> tuple[Manifest, int | None]:
        """Put the researcher's RealityCheck into the slot the model reserved (or before Dispatch)."""
        comps = [c.model_dump() for c in manifest.ui_components_ordered]
        panel = reality_panel(self.state.finding, self.state.evidence)
        at = next((i for i, c in enumerate(comps) if c["component"] == "RealityCheck"), None)
        if panel is None:
            if at is not None:
                comps.pop(at)
            at = None
        elif at is None:
            at = next((i for i, c in enumerate(comps) if c["component"] == "DispatchConsole"), len(comps))
            comps.insert(at, panel)
        else:
            comps[at] = panel
        return Manifest.model_validate({**manifest.model_dump(), "ui_components_ordered": comps}), at

    @listen("haunting")
    async def investigate(self):
        f = self.state.facts
        await self._gather(f"{f.entity} {f.incident_class} {f.summary}")

    @listen("calm")
    async def reassure(self):
        await self._gather(f"false alarm party effects fog lighting {self.state.facts.summary}")

    @listen(or_(investigate, reassure))
    async def compose(self):
        # Don't hold the layout for the web research: if it isn't back yet, the model reserves
        # the RealityCheck slot and the researcher's results fill it in when they land.
        ready = self._research.done()
        if ready:
            self.state.evidence, self.state.finding = await self._reality()
        await self._stage("compose", "Parasail is laying out the station")
        manifest = await compose(
            self.settings,
            self.ai,
            raw=self.raw,
            facts=self.state.facts,
            lore=self.state.lore,
            evidence=self.state.evidence,
            finding=self.state.finding,
            reality_pending=not ready,
            previous_layout=self.previous_layout,
            emit=self.emit,
        )
        if not ready:
            await self.emit({"type": "manifest", "manifest": manifest.model_dump(), "partial": True})
            await self._stage("compose", "Field Researcher is finishing the reality check")
            self.state.evidence, self.state.finding = await self._reality()
            manifest, at = self._fill_reality(manifest)
            if at is not None:
                await self.emit(
                    {"type": "component", "index": at, "component": manifest.ui_components_ordered[at].model_dump()}
                )
        self.state.manifest = manifest
        await self.emit({"type": "manifest", "manifest": manifest.model_dump()})
        await self._stage("done", f"{len(manifest.ui_components_ordered)} components")
