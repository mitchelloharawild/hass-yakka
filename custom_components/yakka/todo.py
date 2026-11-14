"""A to-do list of the group's chores.

Chores that are due or overdue are open items; everything else is shown as
completed. Ticking an item completes the chore in Yakka, and unticking a
completed item undoes its last completion. Recurring chores come back as
open items when they're next due.
"""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Chore
from .const import ACTIONABLE_STATUSES, DOMAIN, STATUS_OVERDUE
from .coordinator import YakkaConfigEntry, YakkaCoordinator
from .entity import YakkaGroupEntity
from .helpers import async_complete, async_undo_last

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YakkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Yakka to-do list."""
    async_add_entities([YakkaTodoList(entry.runtime_data)])


def _describe(chore: Chore, coordinator: YakkaCoordinator) -> str | None:
    bits: list[str] = []
    if chore.status == STATUS_OVERDUE:
        bits.append("Overdue")
    if assignee := coordinator.member_name(chore.current_assignee_id):
        bits.append(f"{assignee}'s turn")
    if chore.description:
        bits.append(chore.description)
    return " · ".join(bits) or None


class YakkaTodoList(YakkaGroupEntity, TodoListEntity):
    """The group's chores as a to-do list."""

    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: YakkaCoordinator) -> None:
        """Initialise the list."""
        super().__init__(coordinator, "chores")

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Chores as to-do items, in Yakka's order (most urgent first)."""
        data = self.coordinator.data
        if data is None:
            return None
        return [
            TodoItem(
                uid=chore.id,
                summary=chore.display_name,
                status=(
                    TodoItemStatus.NEEDS_ACTION
                    if chore.status in ACTIONABLE_STATUSES
                    else TodoItemStatus.COMPLETED
                ),
                due=chore.next_due_at,
                description=_describe(chore, self.coordinator),
            )
            for chore in data.chores.values()
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Tick or untick a chore. Other edits aren't supported."""
        data = self.coordinator.data
        chore = data.chores.get(item.uid or "") if data else None
        if chore is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="chore_not_found"
            )
        is_open = chore.status in ACTIONABLE_STATUSES
        if item.status == TodoItemStatus.COMPLETED and is_open:
            member = await self.coordinator.async_member_for_context(self._context)
            await async_complete(self.coordinator, chore.id, member=member)
        elif item.status == TodoItemStatus.NEEDS_ACTION and not is_open:
            await async_undo_last(self.coordinator, chore.id)
