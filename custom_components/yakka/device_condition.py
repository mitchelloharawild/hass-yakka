"""Device conditions: is a chore in the group due, overdue, or not due."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_CONDITION, CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import ConditionCheckerType
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import ACTIONABLE_STATUSES, DOMAIN, STATUS_OVERDUE
from .helpers import chore_choices, coordinator_for_device

CONF_CHORE_ID = "chore_id"

CONDITION_TYPES = ("is_due", "is_overdue", "is_not_due")

CONDITION_SCHEMA = cv.DEVICE_CONDITION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(CONDITION_TYPES),
        vol.Required(CONF_CHORE_ID): str,
    }
)


async def async_get_conditions(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """The conditions a Yakka group offers."""
    if coordinator_for_device(hass, device_id) is None:
        return []
    return [
        {
            CONF_CONDITION: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: condition_type,
        }
        for condition_type in CONDITION_TYPES
    ]


async def async_get_condition_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Pick the chore."""
    coordinator = coordinator_for_device(hass, config[CONF_DEVICE_ID])
    return {
        "extra_fields": vol.Schema(
            {vol.Required(CONF_CHORE_ID): vol.In(chore_choices(coordinator))}
        )
    }


@callback
def async_condition_from_config(hass: HomeAssistant, config: ConfigType) -> ConditionCheckerType:
    """Check the chore's status as of the latest update."""
    device_id = config[CONF_DEVICE_ID]
    chore_id = config[CONF_CHORE_ID]
    condition_type = config[CONF_TYPE]

    @callback
    def test(hass: HomeAssistant, variables: TemplateVarsType = None) -> bool:
        coordinator = coordinator_for_device(hass, device_id)
        data = coordinator.data if coordinator else None
        chore = data.chores.get(chore_id) if data else None
        if chore is None:
            return False
        if condition_type == "is_due":
            return chore.status in ACTIONABLE_STATUSES
        if condition_type == "is_overdue":
            return chore.status == STATUS_OVERDUE
        return chore.status not in ACTIONABLE_STATUSES

    return test
