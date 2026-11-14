"""The Yakka integration: household chores from a Yakka group."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import YakkaClient
from .const import CONF_BASE_URL, CONF_GROUP_ID, CONF_TOKEN, DOMAIN
from .coordinator import (
    YakkaConfigEntry,
    YakkaCoordinator,
    chore_id_of_entity,
    group_device_identifier,
)
from .services import async_setup_services
from .webhook import async_register_webhook

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: YakkaConfigEntry) -> bool:
    """Set up a Yakka group from a config entry."""
    client = YakkaClient(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_GROUP_ID],
        entry.data[CONF_TOKEN],
    )
    coordinator = YakkaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_webhook(hass, entry)

    _remove_chore_devices(hass, entry)
    remove_stale = _stale_entity_remover(hass, entry)
    remove_stale()
    entry.async_on_unload(coordinator.async_add_listener(remove_stale))
    entry.async_on_unload(coordinator.async_start_chore_events())
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YakkaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: YakkaConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_chore_devices(hass: HomeAssistant, entry: YakkaConfigEntry) -> None:
    """Remove per-chore devices left by early versions; only the group is a device."""
    registry = dr.async_get(hass)
    group = group_device_identifier(entry)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if group not in device.identifiers:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


def _stale_entity_remover(hass: HomeAssistant, entry: YakkaConfigEntry):
    """Remove the entities of chores that were archived or deleted in Yakka."""

    @callback
    def _remove() -> None:
        coordinator = entry.runtime_data
        if not coordinator.last_update_success or coordinator.data is None:
            return
        registry = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
            chore_id = chore_id_of_entity(entry, ent.unique_id)
            if chore_id and chore_id not in coordinator.data.chores:
                registry.async_remove(ent.entity_id)

    return _remove
