"""Actions: yakka.complete_chore and yakka.undo_completion."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CHORE,
    ATTR_COMPLETED_AT,
    ATTR_COMPLETION_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MEMBER,
    ATTR_NOTE,
    DOMAIN,
    SERVICE_COMPLETE_CHORE,
    SERVICE_UNDO_COMPLETION,
)
from .coordinator import YakkaCoordinator
from .helpers import async_complete, async_undo, async_undo_last

COMPLETE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_CHORE): cv.string,
        vol.Optional(ATTR_MEMBER): cv.string,
        vol.Optional(ATTR_NOTE): vol.All(cv.string, vol.Length(max=500)),
        vol.Optional(ATTR_COMPLETED_AT): cv.datetime,
    }
)
UNDO_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Exclusive(ATTR_COMPLETION_ID, "what"): cv.string,
            vol.Exclusive(ATTR_CHORE, "what"): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_COMPLETION_ID, ATTR_CHORE),
)


def _loaded_coordinators(hass: HomeAssistant) -> list[YakkaCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _coordinator(hass: HomeAssistant, entry_id: str | None) -> YakkaCoordinator:
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        return entry.runtime_data
    loaded = _loaded_coordinators(hass)
    if len(loaded) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_required")
    return loaded[0]


def _resolve_chore(
    hass: HomeAssistant, entry_id: str | None, chore: str
) -> tuple[YakkaCoordinator, str]:
    """Accept a Yakka chore id, a chore title, or any of a chore's entity ids."""
    if chore.count(".") == 1 and (ent := er.async_get(hass).async_get(chore)):
        if ent.platform == DOMAIN and ent.config_entry_id:
            coordinator = _coordinator(hass, ent.config_entry_id)
            group_key = coordinator.config_entry.unique_id or ent.config_entry_id
            rest = ent.unique_id.removeprefix(f"{group_key}_")
            for chore_id in coordinator.data.chores:
                if rest.startswith(f"{chore_id}_"):
                    return coordinator, chore_id
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="chore_not_found")

    candidates = [_coordinator(hass, entry_id)] if entry_id else _loaded_coordinators(hass)
    for coordinator in candidates:
        if chore in coordinator.data.chores:
            return coordinator, chore
    wanted = chore.strip().casefold()
    matches = [
        (coordinator, c.id)
        for coordinator in candidates
        for c in coordinator.data.chores.values()
        if c.title.strip().casefold() == wanted
    ]
    if len(matches) == 1:
        return matches[0]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="chore_ambiguous" if matches else "chore_not_found",
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def complete(call: ServiceCall) -> ServiceResponse:
        coordinator, chore_id = _resolve_chore(
            hass, call.data.get(ATTR_CONFIG_ENTRY_ID), call.data[ATTR_CHORE]
        )
        member = call.data.get(ATTR_MEMBER)
        if member is None:
            member = await coordinator.async_member_for_context(call.context)
        completed_at = call.data.get(ATTR_COMPLETED_AT)
        if completed_at is not None and completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=dt_util.get_default_time_zone())
        response = await async_complete(
            coordinator,
            chore_id,
            member=member,
            note=call.data.get(ATTR_NOTE),
            completed_at=completed_at,
        )
        return _summary(response)

    async def undo(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if ATTR_CHORE in call.data:
            coordinator, chore_id = _resolve_chore(hass, entry_id, call.data[ATTR_CHORE])
            response = await async_undo_last(coordinator, chore_id)
        else:
            coordinator = _coordinator(hass, entry_id)
            response = await async_undo(coordinator, call.data[ATTR_COMPLETION_ID])
        summary = _summary(response)
        summary["already_undone"] = bool(response.get("alreadyUndone"))
        return summary

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_CHORE,
        complete,
        schema=COMPLETE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNDO_COMPLETION,
        undo,
        schema=UNDO_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _summary(response: dict[str, Any]) -> dict[str, Any]:
    completion = response.get("completion") or {}
    chore = response.get("chore") or {}
    return {
        "completion_id": completion.get("id"),
        "member": (completion.get("member") or {}).get("name"),
        "deduplicated": bool(response.get("deduplicated")),
        "chore_id": chore.get("id"),
        "status": chore.get("status"),
        "next_due_at": response.get("nextDueAt"),
    }
