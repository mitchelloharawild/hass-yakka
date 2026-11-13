"""The Yakka integration: household chores from a Yakka group."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import YakkaClient
from .const import CONF_BASE_URL, CONF_GROUP_ID, CONF_TOKEN, DOMAIN
from .coordinator import YakkaConfigEntry, YakkaCoordinator
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

    entry.async_on_unload(coordinator.async_add_listener(_stale_device_remover(hass, entry)))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YakkaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: YakkaConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _chore_id_of(entry: YakkaConfigEntry, device: dr.DeviceEntry) -> str | None:
    group_key = entry.unique_id or entry.entry_id
    for domain, ident in device.identifiers:
        if domain == DOMAIN and ident.startswith(f"{group_key}_"):
            return ident[len(group_key) + 1 :]
    return None


def _stale_device_remover(hass: HomeAssistant, entry: YakkaConfigEntry):
    """Remove the devices of chores that were archived or deleted in Yakka."""

    @callback
    def _remove() -> None:
        coordinator = entry.runtime_data
        if not coordinator.last_update_success or coordinator.data is None:
            return
        registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            chore_id = _chore_id_of(entry, device)
            if chore_id and chore_id not in coordinator.data.chores:
                registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)

    return _remove


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: YakkaConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a chore device by hand once the chore is gone."""
    chore_id = _chore_id_of(entry, device)
    if chore_id is None:
        return False  # the group device
    data = entry.runtime_data.data
    return data is None or chore_id not in data.chores
