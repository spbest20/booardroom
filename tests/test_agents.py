"""The Field Researcher's safety nets, with the model and the web stubbed out."""

import asyncio

from app.agents import StationAgents
from app.config import Settings
from app.models import IncidentFacts

FACTS = IncidentFacts(
    incident_class="apparition",
    entity="phantom",
    severity="critical",
    sector="catering_coffee_bar",
    emf_mg=98,
    temp_c=-4,
    summary="s",
)


class FakeSearch:
    def search(self, query, count=4):
        return []


def test_a_failed_researcher_returns_nothing_instead_of_stalling():
    agents = StationAgents(Settings(parasail_api_key="x", ydc_api_key="x"), FakeSearch())

    async def broken(*_):
        raise RuntimeError("agent stalled")

    agents._ask = broken
    assert asyncio.run(agents.research("EMF 98 milligauss at the coffee bar", None)) == ([], None)


def test_intake_takes_the_first_model_that_answers():
    agents = StationAgents(Settings(parasail_api_key="x", ydc_api_key="x"), FakeSearch())

    async def ask(agent, prompt, schema):
        if agent.llm is agents.llm:
            await asyncio.sleep(5)  # the primary engine is having a slow minute
        return FACTS

    agents._ask = ask
    started = asyncio.run(asyncio.wait_for(agents.intake("EMF 98 milligauss, -4C", None), 2))
    assert started.emf_mg == 98
