"""Diagnostics for Yakka. Secrets (group id, token, webhook) are redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_GROUP_ID, CONF_TOKEN, CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET
from .coordinator import YakkaConfigEntry

TO_REDACT = {CONF_GROUP_ID, CONF_TOKEN, CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: YakkaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "chores": [asdict(c) for c in data.chores.values()] if data else None,
        "member_count": len(data.members) if data else None,
    }
