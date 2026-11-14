"""Shared actions: complete and undo, with error handling."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.typing import ConfigType

from .api import Chore, YakkaApiError, YakkaAuthError, YakkaError
from .const import DOMAIN
from .coordinator import YakkaCoordinator, chore_id_of_entity, group_device_identifier

# API error codes caused by what the caller asked for, not by Yakka.
_VALIDATION_CODES = {
    "CHORE_NOT_FOUND",
    "CHORE_ARCHIVED",
    "MEMBER_NOT_FOUND",
    "MEMBER_AMBIGUOUS",
    "MEMBER_ARCHIVED",
    "COMPLETION_NOT_FOUND",
    "COMPLETED_AT_OUT_OF_RANGE",
    "VALIDATION_FAILED",
}


def _raise(err: YakkaError) -> None:
    if isinstance(err, YakkaApiError) and err.code in _VALIDATION_CODES:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="api_rejected",
            translation_placeholders={"code": err.code, "message": str(err)},
        ) from err
    if isinstance(err, YakkaAuthError):
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="request_failed",
        translation_placeholders={"error": str(err)},
    ) from err


def _apply(coordinator: YakkaCoordinator, response: dict[str, Any]) -> None:
    """Patch the returned chore into the coordinator so entities update now."""
    raw = response.get("chore")
    if not isinstance(raw, dict) or coordinator.data is None:
        return
    chore = Chore.from_json(raw)
    chores = dict(coordinator.data.chores)
    if chore.archived:
        chores.pop(chore.id, None)
    else:
        chores[chore.id] = chore
    coordinator.async_set_updated_data(replace(coordinator.data, chores=chores))


async def async_complete(
    coordinator: YakkaCoordinator,
    chore_id: str,
    member: str | None = None,
    note: str | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Complete a chore and update entities from the response."""
    try:
        response = await coordinator.client.complete_chore(
            chore_id, member=member, note=note, completed_at=completed_at
        )
    except YakkaError as err:
        _raise(err)
        raise  # unreachable; keeps type checkers happy
    _apply(coordinator, response)
    return response


async def async_undo(coordinator: YakkaCoordinator, completion_id: str) -> dict[str, Any]:
    """Undo a completion and update entities from the response."""
    try:
        response = await coordinator.client.undo_completion(completion_id)
    except YakkaError as err:
        _raise(err)
        raise
    _apply(coordinator, response)
    return response


async def async_undo_last(coordinator: YakkaCoordinator, chore_id: str) -> dict[str, Any]:
    """Undo a chore's latest completion that hasn't been undone."""
    data = coordinator.data
    chore = data.chores.get(chore_id) if data else None
    if chore is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="chore_not_found")
    last = chore.last_completion
    if last is None or last.undone_at is not None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_undo")
    return await async_undo(coordinator, last.id)


def coordinator_for_device(hass: HomeAssistant, device_id: str) -> YakkaCoordinator | None:
    """The loaded group a Yakka group device belongs to."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is not None
            and entry.domain == DOMAIN
            and entry.state is ConfigEntryState.LOADED
            and group_device_identifier(entry) in device.identifiers
        ):
            return entry.runtime_data
    return None


def chore_choices(coordinator: YakkaCoordinator | None) -> dict[str, str]:
    """The group's chores as {id: title}, for dropdowns."""
    if coordinator is None or coordinator.data is None:
        return {}
    return {c.id: c.display_name for c in coordinator.data.chores.values()}


def member_choices(coordinator: YakkaCoordinator | None) -> dict[str, str]:
    """The group's active members as {id: name}, for dropdowns."""
    if coordinator is None or coordinator.data is None:
        return {}
    return {m.id: m.name for m in coordinator.data.members.values() if not m.archived}


def chores_in_target(
    hass: HomeAssistant, target: ConfigType, *, direct_only: bool = False
) -> set[tuple[str, str]]:
    """The chores a target selects, as {(config entry id, chore id)}.

    Any of a chore's entities selects the chore; a device, area, floor or
    label selects every chore whose entities it covers. With direct_only,
    only entities named outright count.
    """
    selected = async_extract_referenced_entity_ids(
        hass, TargetSelection(target), expand_group=False
    )
    entity_ids = selected.referenced
    if not direct_only:
        entity_ids = entity_ids | selected.indirectly_referenced
    registry = er.async_get(hass)
    chores: set[tuple[str, str]] = set()
    for entity_id in entity_ids:
        ent = registry.async_get(entity_id)
        if ent is None or ent.platform != DOMAIN or ent.config_entry_id is None:
            continue
        entry = hass.config_entries.async_get_entry(ent.config_entry_id)
        if entry is not None and (chore_id := chore_id_of_entity(entry, ent.unique_id)):
            chores.add((entry.entry_id, chore_id))
    return chores


def loaded_coordinator(hass: HomeAssistant, entry_id: str) -> YakkaCoordinator | None:
    """The coordinator of a loaded Yakka config entry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data
