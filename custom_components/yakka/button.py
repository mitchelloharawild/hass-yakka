"""A button per chore that ticks it off."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YakkaConfigEntry
from .entity import YakkaChoreEntity, add_chore_entities
from .helpers import async_complete

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YakkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Yakka buttons."""
    coordinator = entry.runtime_data
    add_chore_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda chore: [CompleteChoreButton(coordinator, chore, "complete")],
    )


class CompleteChoreButton(YakkaChoreEntity, ButtonEntity):
    """Marks the chore as done."""

    async def async_press(self) -> None:
        """Complete the chore."""
        member = await self.coordinator.async_member_for_context(self._context)
        await async_complete(self.coordinator, self.chore_id, member=member)
