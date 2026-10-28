"""Read explicit instrument values straight out of the log.

Numbers like "98 milligauss" or "-4C" are not a judgment call, and the shared
models at the event drop them under load. Code reads the gauges; the model
keeps the judgment (class, entity, sector, severity). Code only fills gaps.
"""

from __future__ import annotations

import re

from .models import IncidentFacts

EMF = re.compile(r"(?:EMF[^0-9\-]{0,40})?(-?\d+(?:\.\d+)?)\s*(?:milligauss|mG\b)", re.I)
TEMP = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*C\b")
PINNED = re.compile(
    r"(\d+)\s+(?:of the \d+\s+)?(?:engineers|people|civilians|attendees|hackers|staff)[^.]{0,40}?(pinned|trapped|stuck)",
    re.I,
)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
NETWORK = re.compile(r"network|switch|router|server rack|wi-?fi|nodes?\b", re.I)


def merge_instruments(raw: str, facts: IncidentFacts) -> IncidentFacts:
    text = re.sub(r"\b(one|two|three|four|five|six)\b", lambda m: str(WORDS[m.group(1).lower()]), raw, flags=re.I)
    updates: dict = {}
    if (m := EMF.findall(text)) and facts.emf_mg is None:
        updates["emf_mg"] = float(m[-1])
    if (m := TEMP.findall(text)) and facts.temp_c is None:
        updates["temp_c"] = float(m[-1])
    if (m := PINNED.search(text)) and not facts.civilians_pinned:
        updates["civilians_pinned"] = int(m.group(1))
        updates["civilians_location"] = facts.civilians_location or facts.sector
    if NETWORK.search(text) and not facts.network_impact and facts.incident_class != "false_alarm":
        updates["network_impact"] = True
    return facts.model_copy(update=updates) if updates else facts
