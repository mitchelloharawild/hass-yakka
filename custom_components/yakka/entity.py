"""Base entities for Yakka."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Chore
from .const import DOMAIN
from .coordinator import YakkaConfigEntry, YakkaCoordinator


def group_device_info(coordinator: YakkaCoordinator) -> DeviceInfo:
    """The device that stands for the whole group."""
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name=entry.title,
        manufacturer="Yakka",
        model="Group",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=coordinator.client.group_url,
    )


class YakkaGroupEntity(CoordinatorEntity[YakkaCoordinator]):
    """An entity about the whole group."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YakkaCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = group_device_info(coordinator)


class YakkaChoreEntity(CoordinatorEntity[YakkaCoordinator]):
    """An entity about one chore. Each chore is its own device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YakkaCoordinator, chore: Chore, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.chore_id = chore.id
        group_key = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{group_key}_{chore.id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{group_key}_{chore.id}")},
            name=chore.title,
            manufacturer="Yakka",
            model="Chore",
            entry_type=DeviceEntryType.SERVICE,
            via_device=(DOMAIN, group_key),
            configuration_url=coordinator.client.group_url,
        )

    @property
    def chore(self) -> Chore | None:
        """The chore's latest data, or None if it's gone."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.chores.get(self.chore_id)

    @property
    def available(self) -> bool:
        """Unavailable once the chore is archived or deleted."""
        return super().available and self.chore is not None


def add_chore_entities(
    coordinator: YakkaCoordinator,
    entry: YakkaConfigEntry,
    async_add_entities: Callable[[Iterable[Entity]], None],
    factory: Callable[[Chore], Iterable[Entity]],
) -> None:
    """Add entities for every chore now, and for new chores as they appear."""
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        if coordinator.data is None:
            return
        # Forget chores that disappeared (their devices are removed), so an
        # unarchived chore gets fresh entities.
        if coordinator.last_update_success:
            known.intersection_update(coordinator.data.chores)
        new = [c for cid, c in coordinator.data.chores.items() if cid not in known]
        if not new:
            return
        known.update(c.id for c in new)
        async_add_entities([e for chore in new for e in factory(chore)])

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
