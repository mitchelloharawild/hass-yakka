"""Device triggers: a chore in the group was completed, undone, or became due.

They fire from yakka_chore_event, which compares each update with the last,
so they work with polling alone; webhooks make them near-instant.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import CHORE_COMPLETED, CHORE_EVENT_TYPES, CHORE_UNDONE, DOMAIN, EVENT_YAKKA_CHORE
from .helpers import chore_choices, coordinator_for_device, member_choices

CONF_CHORE_ID = "chore_id"
CONF_MEMBER_ID = "member_id"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(CHORE_EVENT_TYPES),
        vol.Optional(CONF_CHORE_ID): str,
        vol.Optional(CONF_MEMBER_ID): str,
    }
)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """The triggers a Yakka group offers."""
    if coordinator_for_device(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in CHORE_EVENT_TYPES
    ]


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Optionally narrow the trigger to one chore, and completions to one member."""
    coordinator = coordinator_for_device(hass, config[CONF_DEVICE_ID])
    fields: dict[Any, Any] = {vol.Optional(CONF_CHORE_ID): vol.In(chore_choices(coordinator))}
    if config[CONF_TYPE] in (CHORE_COMPLETED, CHORE_UNDONE):
        fields[vol.Optional(CONF_MEMBER_ID)] = vol.In(member_choices(coordinator))
    return {"extra_fields": vol.Schema(fields)}


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the matching yakka_chore_event."""
    event_data = {CONF_DEVICE_ID: config[CONF_DEVICE_ID], "type": config[CONF_TYPE]}
    if chore_id := config.get(CONF_CHORE_ID):
        event_data["chore_id"] = chore_id
    if (member_id := config.get(CONF_MEMBER_ID)) and config[CONF_TYPE] in (
        CHORE_COMPLETED,
        CHORE_UNDONE,
    ):
        event_data["member_id"] = member_id
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_YAKKA_CHORE,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
