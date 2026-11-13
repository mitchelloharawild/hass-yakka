"""Sensors for Yakka chores and groups."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Chore
from .const import STATUS_DUE, STATUS_OVERDUE, STATUSES
from .coordinator import YakkaConfigEntry, YakkaCoordinator, YakkaData
from .entity import YakkaChoreEntity, YakkaGroupEntity, add_chore_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ChoreSensorDescription(SensorEntityDescription):
    """Describes a per-chore sensor."""

    value_fn: Callable[[Chore, YakkaCoordinator], Any]
    attrs_fn: Callable[[Chore, YakkaCoordinator], dict[str, Any]] | None = None


def _status_attrs(chore: Chore, coordinator: YakkaCoordinator) -> dict[str, Any]:
    return {
        "chore_id": chore.id,
        "title": chore.title,
        "icon_emoji": chore.icon,
        "description": chore.description,
        "checklist": chore.checklist,
        "due_today": chore.due_today,
        "missed_count": chore.missed_count,
        "next_due_at": chore.next_due_at,
        "overdue_at": chore.overdue_at,
        "schedule": chore.rrule,
        "anchor": chore.anchor,
        "assignee_mode": chore.assignee_mode,
        "assignee": coordinator.member_name(chore.current_assignee_id),
    }


def _last_attrs(chore: Chore, coordinator: YakkaCoordinator) -> dict[str, Any]:
    last = chore.last_completion
    if last is None:
        return {}
    return {
        "completion_id": last.id,
        "member": last.member_name,
        "source": last.source,
        "note": last.note,
    }


CHORE_SENSORS: tuple[ChoreSensorDescription, ...] = (
    ChoreSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        value_fn=lambda c, _: c.status,
        attrs_fn=_status_attrs,
    ),
    ChoreSensorDescription(
        key="next_due",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, _: c.next_due_at,
    ),
    ChoreSensorDescription(
        key="last_completed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, _: c.last_completion.completed_at if c.last_completion else None,
        attrs_fn=_last_attrs,
    ),
    ChoreSensorDescription(
        key="assignee",
        value_fn=lambda c, coord: coord.member_name(c.current_assignee_id),
    ),
)


@dataclass(frozen=True, kw_only=True)
class GroupSensorDescription(SensorEntityDescription):
    """Describes a per-group sensor."""

    statuses: frozenset[str]


GROUP_SENSORS: tuple[GroupSensorDescription, ...] = (
    GroupSensorDescription(
        key="due_chores",
        state_class=SensorStateClass.MEASUREMENT,
        statuses=frozenset({STATUS_DUE, STATUS_OVERDUE}),
    ),
    GroupSensorDescription(
        key="overdue_chores",
        state_class=SensorStateClass.MEASUREMENT,
        statuses=frozenset({STATUS_OVERDUE}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YakkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Yakka sensors."""
    coordinator = entry.runtime_data
    async_add_entities(GroupCountSensor(coordinator, d) for d in GROUP_SENSORS)
    add_chore_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda chore: [ChoreSensor(coordinator, chore, d) for d in CHORE_SENSORS],
    )


class ChoreSensor(YakkaChoreEntity, SensorEntity):
    """A sensor about one chore."""

    entity_description: ChoreSensorDescription

    def __init__(
        self,
        coordinator: YakkaCoordinator,
        chore: Chore,
        description: ChoreSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, chore, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | datetime | None:
        """The sensor's value."""
        chore = self.chore
        return self.entity_description.value_fn(chore, self.coordinator) if chore else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes."""
        chore = self.chore
        if chore is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(chore, self.coordinator)


class GroupCountSensor(YakkaGroupEntity, SensorEntity):
    """How many of the group's chores are due (or overdue)."""

    entity_description: GroupSensorDescription

    def __init__(self, coordinator: YakkaCoordinator, description: GroupSensorDescription) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _matching(self, data: YakkaData) -> list[Chore]:
        return [c for c in data.chores.values() if c.status in self.entity_description.statuses]

    @property
    def native_value(self) -> int | None:
        """Number of matching chores."""
        data = self.coordinator.data
        return len(self._matching(data)) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The matching chores' titles."""
        data = self.coordinator.data
        return {"chores": [c.title for c in self._matching(data)]} if data else None
