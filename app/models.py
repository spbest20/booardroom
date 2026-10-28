"""Shapes: what we read out of a raw incident, and the UI manifest the model composes.

Every component the model may choose is a typed model here; the server
validates each one as it streams in and drops anything that does not fit.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

SECTORS = (
    "entrance",
    "main_stage",
    "catering_coffee_bar",
    "workshop",
    "lounge",
    "network_closet",
    "green_room",
)
Sector = Literal[SECTORS]
Status = Literal["ok", "warning", "danger"]


class IncidentFacts(BaseModel):
    """Structured reading of the raw stream (extracted by Parasail)."""

    incident_class: Literal["apparition", "poltergeist", "possession", "network_haunt", "false_alarm"]
    entity: str = Field(description="What the reports describe, e.g. 'level-5 phantom'; 'none' for false alarms")
    severity: Literal["low", "elevated", "critical"]
    sector: Sector
    emf_mg: float | None = None
    temp_c: float | None = None
    civilians_pinned: int = 0
    civilians_location: Sector | None = None
    network_impact: bool = False
    spreading_to: list[Sector] = []
    summary: str = Field(description="One sentence, plain language")


# --- Components the model can place ------------------------------------------


class ThreatBanner(BaseModel):
    component: Literal["ThreatBanner"]
    headline: str
    entity: str
    severity: Literal["low", "elevated", "critical"]


class EMFRadar(BaseModel):
    component: Literal["EMFRadar"]
    current_value: float
    baseline_max: float
    trend: Literal["rising", "steady", "falling"]
    status: Status
    refresh_rate_ms: int = 100


class Thermometer(BaseModel):
    component: Literal["Thermometer"]
    temp_c: float
    baseline_min_c: float
    status: Status


class CivilianMarker(BaseModel):
    sector: Sector
    count: int
    status: Literal["pinned", "evacuating", "safe"]


class Floorplan(BaseModel):
    component: Literal["Floorplan"]
    highlight_sector: Sector
    ghost_sector: Sector
    isolated_zones: list[Sector] = []
    civilians: list[CivilianMarker] = []


class CivilianTracker(BaseModel):
    component: Literal["CivilianTracker"]
    pinned: int
    location: Sector
    status: Status
    extraction_note: str


class NetworkNodes(BaseModel):
    component: Literal["NetworkNodes"]
    nodes_affected: int
    total_nodes: int = 12
    note: str


class CounterMeasure(BaseModel):
    name: str
    why: str


class CounterMeasureSelector(BaseModel):
    component: Literal["CounterMeasureSelector"]
    target_entity: str
    options: list[CounterMeasure]
    recommended: str


class Claim(BaseModel):
    text: str
    url: str


class RealityCheck(BaseModel):
    component: Literal["RealityCheck"]
    verdict: str
    claims: list[Claim]


class DispatchConsole(BaseModel):
    component: Literal["DispatchConsole"]
    channel: str = "#loft-incident"
    draft: str
    priority: Literal["routine", "urgent", "critical"]


class CalmStatus(BaseModel):
    component: Literal["CalmStatus"]
    message: str
    explanation: str


Component = Annotated[
    ThreatBanner
    | EMFRadar
    | Thermometer
    | Floorplan
    | CivilianTracker
    | NetworkNodes
    | CounterMeasureSelector
    | RealityCheck
    | DispatchConsole
    | CalmStatus,
    Field(discriminator="component"),
]

Theme = Literal["spectral-goth-dark", "ecto-green", "blood-moon", "calm-dawn"]


class Manifest(BaseModel):
    theme: Theme
    headline: str
    ui_components_ordered: list[Component]
