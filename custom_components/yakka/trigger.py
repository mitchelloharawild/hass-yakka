"""Triggers for the automation editor's "By target" view.

yakka.chore_completed, chore_undone, chore_due and chore_overdue fire for the
chores their target selects: one of a chore's entities for that chore, or the
group's device for all of them. Like the device triggers they fire from
yakka_chore_event, so they work with polling alone.

Who completed a chore isn't a trigger option; the yakka.chore_completed_by
condition checks that.
"""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol

from homeassistant.const import CONF_TARGET
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.trigger import Trigger, TriggerActionRunner, TriggerConfig
from homeassistant.helpers.typing import ConfigType

from .const import CHORE_COMPLETED, CHORE_DUE, CHORE_OVERDUE, CHORE_UNDONE, EVENT_YAKKA_CHORE
from .helpers import chores_in_target

TRIGGER_SCHEMA = vol.Schema({vol.Required(CONF_TARGET): cv.TARGET_FIELDS})

_DESCRIPTIONS = {
    CHORE_COMPLETED: "completed",
    CHORE_UNDONE: "completion undone",
    CHORE_DUE: "became due",
    CHORE_OVERDUE: "became overdue",
}


class ChoreEventTrigger(Trigger):
    """Fires when a yakka_chore_event of one type is for a targeted chore."""

    _event_type: str

    @override
    @classmethod
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        """Validate config."""
        return TRIGGER_SCHEMA(config)

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Keep the target; it's resolved per event so new chores are covered."""
        super().__init__(hass, config)
        self._target: dict[str, Any] = config.target or {}

    @override
    async def async_attach_runner(self, run_action: TriggerActionRunner) -> CALLBACK_TYPE:
        """Listen for yakka_chore_event."""

        @callback
        def event_filter(event_data: dict[str, Any]) -> bool:
            return event_data.get("type") == self._event_type

        @callback
        def handle(event: Event) -> None:
            data = event.data
            if (data.get("config_entry_id"), data.get("chore_id")) not in chores_in_target(
                self._hass, self._target
            ):
                return
            run_action(
                {key: value for key, value in data.items() if key != "type"},
                f"Yakka chore {data.get('chore')} {_DESCRIPTIONS[self._event_type]}",
                event.context,
            )

        return self._hass.bus.async_listen(EVENT_YAKKA_CHORE, handle, event_filter=event_filter)


def _trigger(event_type: str) -> type[ChoreEventTrigger]:
    name = f"Chore{event_type.title()}Trigger"
    return type(name, (ChoreEventTrigger,), {"_event_type": event_type})


TRIGGERS: dict[str, type[Trigger]] = {
    f"chore_{event_type}": _trigger(event_type)
    for event_type in (CHORE_COMPLETED, CHORE_UNDONE, CHORE_DUE, CHORE_OVERDUE)
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """The triggers Yakka offers."""
    return TRIGGERS
