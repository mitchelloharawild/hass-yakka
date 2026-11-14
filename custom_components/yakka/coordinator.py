"""Polls Yakka for a group's chores and members."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Chore, Member, YakkaAuthError, YakkaClient, YakkaError
from .const import (
    ACTIONABLE_STATUSES,
    CHORE_COMPLETED,
    CHORE_DUE,
    CHORE_ENTITY_KEYS,
    CHORE_OVERDUE,
    CHORE_UNDONE,
    CONF_DEFAULT_MEMBER,
    CONF_MATCH_USERS,
    CONF_SCAN_INTERVAL,
    CONF_USER_MEMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_YAKKA_CHORE,
    STATUS_OVERDUE,
    USE_DEFAULT_MEMBER,
)

_LOGGER = logging.getLogger(__name__)

type YakkaConfigEntry = ConfigEntry[YakkaCoordinator]


def group_key(entry: ConfigEntry) -> str:
    """The key the group's devices and entities are named with."""
    return entry.unique_id or entry.entry_id


def group_device_identifier(entry: ConfigEntry) -> tuple[str, str]:
    """The device registry identifier of the group's device."""
    return (DOMAIN, group_key(entry))


def chore_id_of_entity(entry: ConfigEntry, unique_id: str) -> str | None:
    """The chore a chore entity's unique id belongs to, or None."""
    rest = unique_id.removeprefix(f"{group_key(entry)}_")
    if rest == unique_id:
        return None
    for key in CHORE_ENTITY_KEYS:
        if rest.endswith(f"_{key}") and len(rest) > len(key) + 1:
            return rest[: -len(key) - 1]
    return None


def chore_changes(old: Chore, new: Chore) -> list[str]:
    """What happened to a chore between two updates.

    "due" means the chore needs doing now, so a chore that skips straight
    from upcoming to overdue between updates is both "due" and "overdue".
    Yakka's last completion is the latest one that hasn't been undone, so a
    newer one means a completion and an older one (or none) means an undo.
    """
    changes: list[str] = []
    before, after = old.last_completion, new.last_completion
    if after and (before is None or after.id != before.id):
        newer = (
            before is None
            or after.completed_at is None
            or before.completed_at is None
            or after.completed_at >= before.completed_at
        )
        changes.append(CHORE_COMPLETED if newer else CHORE_UNDONE)
    elif before and after is None:
        changes.append(CHORE_UNDONE)
    if new.status in ACTIONABLE_STATUSES and old.status not in ACTIONABLE_STATUSES:
        changes.append(CHORE_DUE)
    if new.status == STATUS_OVERDUE and old.status != STATUS_OVERDUE:
        changes.append(CHORE_OVERDUE)
    return changes


@dataclass(slots=True)
class YakkaData:
    """A snapshot of the group."""

    chores: dict[str, Chore] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)


class YakkaCoordinator(DataUpdateCoordinator[YakkaData]):
    """Keeps one group's chores and members up to date."""

    config_entry: YakkaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: YakkaConfigEntry, client: YakkaClient) -> None:
        """Initialise the coordinator."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=(timedelta(minutes=minutes) if minutes else DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._previous: YakkaData | None = None

    async def _async_update_data(self) -> YakkaData:
        try:
            chores, members = await asyncio.gather(
                self.client.get_chores(), self.client.get_members()
            )
        except YakkaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except YakkaError as err:
            raise UpdateFailed(f"Error talking to Yakka: {err}") from err
        return YakkaData(
            chores={c.id: c for c in chores},
            members={m.id: m for m in members},
        )

    @callback
    def async_start_chore_events(self) -> CALLBACK_TYPE:
        """Fire yakka_chore_event for changes seen from now on."""
        self._previous = self.data
        return self.async_add_listener(self._async_fire_chore_events)

    @callback
    def _async_fire_chore_events(self) -> None:
        previous, current = self._previous, self.data
        if current is None or current is previous:
            return
        self._previous = current
        if previous is None:
            return
        device = dr.async_get(self.hass).async_get_device(
            identifiers={group_device_identifier(self.config_entry)}
        )
        for chore_id, new in current.chores.items():
            old = previous.chores.get(chore_id)
            if old is None:
                continue
            for change in chore_changes(old, new):
                completion = old.last_completion if change == CHORE_UNDONE else new.last_completion
                if change in (CHORE_DUE, CHORE_OVERDUE):
                    completion = None
                self.hass.bus.async_fire(
                    EVENT_YAKKA_CHORE,
                    {
                        "config_entry_id": self.config_entry.entry_id,
                        "device_id": device.id if device else None,
                        "chore_id": chore_id,
                        "chore": new.title,
                        "type": change,
                        "completion_id": completion.id if completion else None,
                        "member_id": completion.member_id if completion else None,
                        "member": completion.member_name if completion else None,
                    },
                )

    def member_name(self, member_id: str | None) -> str | None:
        """Name of an active member, or None."""
        if member_id and self.data and (m := self.data.members.get(member_id)):
            return m.name
        return None

    async def async_member_for_context(self, context: Context | None) -> str | None:
        """Pick the Yakka member to record a completion from Home Assistant as.

        1. If the Home Assistant user who triggered the action is linked to a
           member in the options, and that member is still active, that
           member. A user linked to "the default" skips straight to step 3.
        2. If the "match users" option is on and the user has the same name
           as exactly one active Yakka member (ignoring case), that member.
        3. The default member from the options, if any.
        4. None, which Yakka records as "Automation".
        """
        options = self.config_entry.options
        user_id = context.user_id if context else None
        linked = options.get(CONF_USER_MEMBERS, {}).get(user_id) if user_id else None
        if linked and linked != USE_DEFAULT_MEMBER and self.data:
            member = self.data.members.get(linked)
            if member and not member.archived:
                return member.id
        if linked != USE_DEFAULT_MEMBER and options.get(CONF_MATCH_USERS, True) and user_id:
            user = await self.hass.auth.async_get_user(user_id)
            if user and user.name and self.data:
                wanted = user.name.strip().casefold()
                matches = [
                    m.id
                    for m in self.data.members.values()
                    if not m.archived and m.name.strip().casefold() == wanted
                ]
                if len(matches) == 1:
                    return matches[0]
        default = options.get(CONF_DEFAULT_MEMBER)
        if default and self.data and default in self.data.members:
            return default
        return None
