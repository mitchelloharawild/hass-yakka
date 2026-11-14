"""Device actions: complete a chore in the group, or undo its last completion."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import DOMAIN
from .helpers import (
    async_complete,
    async_undo_last,
    chore_choices,
    coordinator_for_device,
    member_choices,
)

CONF_CHORE_ID = "chore_id"
CONF_MEMBER_ID = "member_id"
CONF_NOTE = "note"

ACTION_COMPLETE = "complete"
ACTION_UNDO = "undo_last_completion"
ACTION_TYPES = (ACTION_COMPLETE, ACTION_UNDO)

ACTION_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(ACTION_TYPES),
        vol.Required(CONF_CHORE_ID): str,
        vol.Optional(CONF_MEMBER_ID): str,
        vol.Optional(CONF_NOTE): vol.All(str, vol.Length(max=500)),
    }
)


async def async_get_actions(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """The actions a Yakka group offers."""
    if coordinator_for_device(hass, device_id) is None:
        return []
    return [
        {CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: action_type}
        for action_type in ACTION_TYPES
    ]


async def async_get_action_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Pick the chore, and for completions who did it and a note."""
    coordinator = coordinator_for_device(hass, config[CONF_DEVICE_ID])
    fields: dict[Any, Any] = {vol.Required(CONF_CHORE_ID): vol.In(chore_choices(coordinator))}
    if config[CONF_TYPE] == ACTION_COMPLETE:
        fields[vol.Optional(CONF_MEMBER_ID)] = vol.In(member_choices(coordinator))
        fields[vol.Optional(CONF_NOTE)] = str
    return {"extra_fields": vol.Schema(fields)}


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: ConfigType,
    variables: TemplateVarsType,
    context: Context | None,
) -> None:
    """Complete the chore, or undo its last completion."""
    coordinator = coordinator_for_device(hass, config[CONF_DEVICE_ID])
    if coordinator is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    chore_id = config[CONF_CHORE_ID]
    if config[CONF_TYPE] == ACTION_UNDO:
        await async_undo_last(coordinator, chore_id)
        return
    if coordinator.data is None or chore_id not in coordinator.data.chores:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="chore_not_found")
    member = config.get(CONF_MEMBER_ID) or await coordinator.async_member_for_context(context)
    await async_complete(coordinator, chore_id, member=member, note=config.get(CONF_NOTE))
