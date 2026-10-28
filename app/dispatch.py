"""The Dispatch button: posts the alert to the venue's #loft-incident channel.

The organizers made the venue's Discord webhook the dispatch path for the event
(One's Discord send was returning 401). The URL lives in .env, never in the repo.
Every post starts with the team handle, because a webhook cannot attribute a
post to a team on its own. A failed write is reported, never retried blindly.
"""

from __future__ import annotations

import httpx

from .config import Settings

DISCORD_LIMIT = 1900  # Discord rejects messages over 2,000 characters


def with_team(team: str, content: str) -> str:
    """Prefix the team handle unless the line already starts with it."""
    team = team or "team-??"
    return content if content.startswith(team) else f"{team} · {content}"


def dispatch(settings: Settings, content: str) -> dict:
    content = with_team(settings.team, content.strip())[:DISCORD_LIMIT]
    if settings.dispatch_mode != "live":
        return {"sent": False, "via": "dry-run", "content": content, "detail": "DISPATCH_MODE=dry: not posted"}
    if not settings.discord_webhook_url:
        return {"sent": False, "via": "none", "content": content, "detail": "DISCORD_WEBHOOK_URL is not set"}
    try:
        resp = httpx.post(settings.discord_webhook_url, json={"content": content}, timeout=20)
    except httpx.TimeoutException:
        # The post may have landed: say so instead of sending it twice.
        return {
            "sent": False,
            "via": "webhook",
            "content": content,
            "detail": "timeout: check #loft-incident before resending",
        }
    return {"sent": resp.is_success, "via": "webhook", "content": content, "detail": f"HTTP {resp.status_code}"}
