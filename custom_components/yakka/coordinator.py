"""Polls Yakka for a group's chores and members."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Chore, Member, YakkaAuthError, YakkaClient, YakkaError
from .const import (
    CONF_DEFAULT_MEMBER,
    CONF_MATCH_USERS,
    CONF_SCAN_INTERVAL,
    CONF_USER_MEMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    USE_DEFAULT_MEMBER,
)

_LOGGER = logging.getLogger(__name__)

type YakkaConfigEntry = ConfigEntry[YakkaCoordinator]


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
