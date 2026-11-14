"""Conditions for the automation editor's "By target" view.

yakka.chore_is_due, chore_is_overdue and chore_is_not_due check the status of
the chores their target selects; yakka.chore_completed_by checks who did a
chore's latest completion. With several chores selected, "behavior" says
whether any or all of them must match.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Unpack, override

import voluptuous as vol

from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import (
    ATTR_BEHAVIOR,
    BEHAVIOR_ALL,
    BEHAVIOR_ANY,
    Condition,
    ConditionChecker,
    ConditionCheckParams,
    ConditionConfig,
)
from homeassistant.helpers.typing import ConfigType

from .api import Chore
from .const import ACTIONABLE_STATUSES, STATUS_OVERDUE
from .helpers import chores_in_target, loaded_coordinator

ATTR_MEMBER = "member"

_BEHAVIOR = vol.In([BEHAVIOR_ANY, BEHAVIOR_ALL])

STATUS_CONDITION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Optional(CONF_OPTIONS, default={}): {
            vol.Optional(ATTR_BEHAVIOR, default=BEHAVIOR_ANY): _BEHAVIOR
        },
    }
)
COMPLETED_BY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required(CONF_OPTIONS): {
            vol.Required(ATTR_MEMBER): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_BEHAVIOR, default=BEHAVIOR_ANY): _BEHAVIOR,
        },
    }
)


class ChoreCondition(Condition):
    """Tests the targeted chores, as of the latest update."""

    _schema: vol.Schema = STATUS_CONDITION_SCHEMA

    @override
    @classmethod
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        """Validate config."""
        return cls._schema(config)

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        """Keep the target and options."""
        super().__init__(hass, config)
        self._target: dict[str, Any] = config.target or {}
        self._options: dict[str, Any] = config.options or {}

    def matches(self, chore: Chore) -> bool:
        """Whether one chore passes."""
        raise NotImplementedError

    @override
    async def async_get_checker(self) -> ConditionChecker:
        """Check the targeted chores; with none, the condition fails."""
        combine: Callable[[Any], bool] = (
            all if self._options.get(ATTR_BEHAVIOR) == BEHAVIOR_ALL else any
        )

        def test(**kwargs: Unpack[ConditionCheckParams]) -> bool:
            chores = []
            for entry_id, chore_id in chores_in_target(self._hass, self._target):
                coordinator = loaded_coordinator(self._hass, entry_id)
                data = coordinator.data if coordinator else None
                if data and (c := data.chores.get(chore_id)):
                    chores.append(c)
            return bool(chores) and combine(self.matches(c) for c in chores)

        return test


class ChoreIsDue(ChoreCondition):
    """The chore is due or overdue."""

    def matches(self, chore: Chore) -> bool:
        return chore.status in ACTIONABLE_STATUSES


class ChoreIsOverdue(ChoreCondition):
    """The chore is overdue."""

    def matches(self, chore: Chore) -> bool:
        return chore.status == STATUS_OVERDUE


class ChoreIsNotDue(ChoreCondition):
    """The chore is neither due nor overdue."""

    def matches(self, chore: Chore) -> bool:
        return chore.status not in ACTIONABLE_STATUSES


class ChoreCompletedBy(ChoreCondition):
    """The chore's latest completion was by a member, given by name or id."""

    _schema = COMPLETED_BY_SCHEMA

    def matches(self, chore: Chore) -> bool:
        last = chore.last_completion
        if last is None or last.undone_at is not None:
            return False
        wanted = self._options[ATTR_MEMBER].strip()
        return wanted == last.member_id or (
            last.member_name is not None
            and last.member_name.strip().casefold() == wanted.casefold()
        )


CONDITIONS: dict[str, type[Condition]] = {
    "chore_is_due": ChoreIsDue,
    "chore_is_overdue": ChoreIsOverdue,
    "chore_is_not_due": ChoreIsNotDue,
    "chore_completed_by": ChoreCompletedBy,
}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """The conditions Yakka offers."""
    return CONDITIONS
