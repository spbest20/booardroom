"""Settings from the environment (.env is loaded by the server)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    ydc_api_key: str = field(default_factory=lambda: _get("YDC_API_KEY"))
    parasail_api_key: str = field(default_factory=lambda: _get("PARASAIL_API_KEY"))
    # Fast first token matters: the interface streams while the model writes.
    compose_model: str = field(default_factory=lambda: _get("PARASAIL_COMPOSE_MODEL", "parasail-gpt-oss-120b-fast"))
    extract_model: str = field(default_factory=lambda: _get("PARASAIL_EXTRACT_MODEL", "parasail-gpt-oss-120b-fast"))
    fallback_model: str = field(default_factory=lambda: _get("PARASAIL_FALLBACK_MODEL", "parasail-llama-33-70b-fp8"))
    embed_model: str = field(default_factory=lambda: _get("PARASAIL_EMBED_MODEL", "parasail-bge-m3"))

    # The venue webhook for #loft-incident, from the event page. Never commit it.
    discord_webhook_url: str = field(default_factory=lambda: _get("DISCORD_WEBHOOK_URL"))
    # "dry" shows dispatches in the UI only; "live" posts them to #loft-incident.
    dispatch_mode: str = field(default_factory=lambda: _get("DISPATCH_MODE", "dry"))
    # Self-chosen handle (lowercase, digits, dashes); every post starts with it.
    team: str = field(default_factory=lambda: _get("TEAM_HANDLE"))

    port: int = field(default_factory=lambda: int(_get("PORT", "8666")))
