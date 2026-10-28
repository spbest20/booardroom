"""Lore retrieval: which counter-measures fit this entity.

The library is embedded once with Parasail (bge-m3) and searched by cosine
similarity. If the embeddings engine is busy, word overlap ranks instead, so
the station never stalls on retrieval.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from openai import OpenAI

LORE_PATH = Path(__file__).resolve().parent.parent / "data" / "lore.json"


def _doc(entry: dict) -> str:
    return f"{entry['name'].replace('_', ' ')}: counters {entry['counters']}. {entry['lore']}"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}


class LoreIndex:
    def __init__(self, client: OpenAI, model: str):
        self.client, self.model = client, model
        self.entries: list[dict] = json.loads(LORE_PATH.read_text())
        self._vectors: list[list[float]] | None = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]

    def search(self, query: str, k: int = 3) -> tuple[list[dict], str]:
        """Top-k entries and the method used ("embeddings" or "keyword")."""
        try:
            if self._vectors is None:
                self._vectors = self._embed([_doc(e) for e in self.entries])
            q = self._embed([query])[0]
            scored = [(_cosine(q, v), e) for v, e in zip(self._vectors, self.entries, strict=True)]
            method = "embeddings"
        except Exception:  # noqa: BLE001 - a busy engine falls back, never stalls the UI
            qw = _words(query)
            scored = [(len(qw & _words(_doc(e))), e) for e in self.entries]
            method = "keyword"
        scored.sort(key=lambda s: s[0], reverse=True)
        return [e for _, e in scored[:k]], method
