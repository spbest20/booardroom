"""The station's CrewAI agents. Each has one role, its own tools, and a typed answer.

  Intake Analyst   - reads the raw stream into IncidentFacts; runs on two models
                     at once and the first valid answer wins (shared engines are
                     fast one minute and slow the next)
  Field Researcher - starts from the raw report, in parallel with the Analyst;
                     decides what to search with its You.com tool and returns what
                     it concluded; every URL its tool saw is recorded, so the
                     composer can only cite what was actually found

Both think on Parasail. The layout itself is streamed by app.parasail.compose,
because the browser needs each component the moment it is written.
"""

from __future__ import annotations

import asyncio

from crewai import LLM, Agent
from crewai.tools import tool
from pydantic import BaseModel, Field

from .config import Settings
from .grounding import Evidence, YouSearch
from .instruments import merge_instruments
from .models import IncidentFacts
from .parasail import EXTRACT_PROMPT, PARASAIL_URL, _transient

RESEARCH_TIMEOUT_S = 20
INTAKE_TIMEOUT_S = 45
LLM_TIMEOUT_S = 20
MAX_SEARCHES = 2


class ResearchClaim(BaseModel):
    text: str = Field(description="One short factual sentence, in your own words, supported by the result")
    url: str = Field(description="The URL of the search result that supports it, exactly as returned")


class ResearchBrief(BaseModel):
    queries: list[str] = Field(description="The searches you ran, in order")
    finding: str = Field(description="One sentence: the most plausible mundane explanation, or that none fits")
    claims: list[ResearchClaim] = Field(default=[], description="Two or three claims from results you saw, best first")


def _llm(settings: Settings, model: str) -> LLM:
    # Bare model id + provider="openai": the prefix form falls through to LiteLLM.
    # A short timeout: a dead connection to a shared engine must fail over, not hang the station.
    return LLM(
        model=model,
        provider="openai",
        base_url=PARASAIL_URL,
        api_key=settings.parasail_api_key,
        temperature=0,
        timeout=LLM_TIMEOUT_S,
        max_retries=1,
    )


class StationAgents:
    def __init__(self, settings: Settings, search: YouSearch):
        self.s, self.search = settings, search
        self.llm = _llm(settings, settings.extract_model)
        self.fallback = _llm(settings, settings.fallback_model)

    async def _ask(self, agent: Agent, prompt: str, schema: type):
        """Shared engines get overloaded at the event: retry, then switch the agent's model."""
        for attempt in range(4):
            if attempt == 2:
                agent.llm = self.fallback
            try:
                out = await agent.kickoff_async(prompt, response_format=schema)
            except Exception as e:  # noqa: BLE001
                if not _transient(e) or attempt == 3:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return out.pydantic or schema.model_validate_json(out.raw)

    async def _race(self, make_agent, prompt: str, schema: type):
        """Ask the same agent on both models; the first valid answer wins, the other is cancelled."""
        tasks = [asyncio.create_task(self._ask(make_agent(llm), prompt, schema)) for llm in (self.llm, self.fallback)]
        error: Exception | None = None
        try:
            for done in asyncio.as_completed(tasks):
                try:
                    return await done
                except Exception as e:  # noqa: BLE001 - the other model may still answer
                    error = e
            raise error or RuntimeError("no model answered")
        finally:
            for t in tasks:
                t.cancel()

    async def intake(self, raw: str, previous: IncidentFacts | None) -> IncidentFacts:
        def analyst(llm: LLM) -> Agent:
            return Agent(
                role="Intake Analyst",
                goal="Turn a panicked incident report into exact, structured facts",
                backstory=EXTRACT_PROMPT,
                llm=llm,
            )

        prompt = f"Previous facts: {previous.model_dump_json() if previous else 'none'}\n\nNew log:\n{raw}"
        facts = await asyncio.wait_for(self._race(analyst, prompt, IncidentFacts), INTAKE_TIMEOUT_S)
        return merge_instruments(raw, facts)

    async def research(self, raw: str, previous: IncidentFacts | None) -> tuple[list[Evidence], ResearchBrief | None]:
        """Agent-led web research from the raw report. Returns no evidence if the agent fails or stalls."""
        found: list[Evidence] = []
        calls: list[str] = []
        search = self.search

        @tool("you_web_search")
        def you_web_search(query: str) -> str:
            """Search the live web with You.com. Returns titles, URLs and passages."""
            if len(calls) >= MAX_SEARCHES:  # every search is a round trip the operator waits on
                return "Search budget used. Report your finding from the results you already have."
            calls.append(query)
            hits = search.search(query, count=3)
            found.extend(hits)
            return "\n".join(f"- {h.title} ({h.url}): {h.text[:400]}" for h in hits) or "no results"

        researcher = Agent(
            role="Field Researcher",
            goal="Find real-world, non-paranormal explanations for the readings, with sources",
            backstory=(
                "You are the station's skeptic with a search engine. Search for what could physically cause the "
                "readings (EMF levels, cold spots, failing network gear) in an office building. Run at most two "
                "focused searches with you_web_search, then report what you found, with two or three claims "
                "that each cite the result supporting them. Never invent a source."
            ),
            tools=[you_web_search],
            llm=self.llm,
            max_iter=3,
        )
        prompt = f"Earlier facts: {previous.model_dump_json() if previous else 'none'}\n\nIncident report:\n{raw}"
        brief = None
        try:
            brief = await asyncio.wait_for(self._ask(researcher, prompt, ResearchBrief), RESEARCH_TIMEOUT_S)
            brief.queries = calls or brief.queries  # what the tool actually ran, not what the agent recalls
        except Exception:  # noqa: BLE001 - a stalled agent leaves the fixed search to the Flow, never stalls the UI
            pass
        seen, unique = set(), []
        for e in found:
            if e.url and e.url not in seen:
                seen.add(e.url)
                unique.append(e)
        return unique[:6], brief
