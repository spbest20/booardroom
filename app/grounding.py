"""You.com grounding for the Reality Check panel.

For every incident the station asks the live web what could explain the
readings. The composer may only cite URLs that came back from this search;
anything else is stripped before it reaches the screen.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import httpx

from .models import IncidentFacts

SEARCH_URL = "https://ydc-index.io/v1/search"


@dataclass
class Evidence:
    url: str
    title: str
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


def reality_query(facts: IncidentFacts) -> str:
    signs = []
    if facts.emf_mg is not None:
        signs.append(f"EMF reading of {facts.emf_mg:g} milligauss")
    if facts.temp_c is not None:
        signs.append(f"sudden indoor temperature drop to {facts.temp_c:g} C")
    if facts.network_impact:
        signs.append("network equipment failing")
    if not signs:
        signs.append(facts.summary)
    return "what causes " + " and ".join(signs) + " in an office building"


class YouSearch:
    def __init__(self, api_key: str):
        self.client = httpx.Client(headers={"X-API-Key": api_key}, timeout=20)

    def search(self, query: str, count: int = 4) -> list[Evidence]:
        body = {"query": query, "count": count}
        resp = self.client.post(SEARCH_URL, json=body)
        if resp.status_code == 429:
            time.sleep(float(resp.headers.get("Retry-After", "2")))
            resp = self.client.post(SEARCH_URL, json=body)
        resp.raise_for_status()
        results = resp.json().get("results", {})
        hits = [*results.get("web", []), *results.get("news", [])] if isinstance(results, dict) else []
        out = []
        for h in hits[:count]:
            text = " ".join([h.get("description", ""), *(h.get("snippets") or [])]).strip()
            out.append(Evidence(h.get("url", ""), h.get("title", ""), text[:700]))
        return out
