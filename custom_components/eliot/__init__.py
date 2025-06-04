"""Home Assistant integration for Eliot smart desks."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .ble import EliotDeskClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "button", "number", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Eliot desk from a config entry."""

    address = entry.data["address"]
    name = entry.data.get("name", address)

    client = EliotDeskClient(hass, address)

    async def _async_update_data():
        try:
            height = await client.get_height()
            return {"height_mm": height, "locked": client.is_locked}
        except Exception as err:
            raise UpdateFailed(err) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"eliot_desk_{address}",
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        update_method=_async_update_data,
    )

    # first refresh
    await coordinator.async_config_entry_first_refresh()

    # callbacks to push async updates from notifications
    client.set_lock_callback(
        lambda locked: coordinator.async_set_updated_data(
            {"height_mm": client.height_mm, "locked": locked}
        )
    )
    client.set_height_callback(
        lambda height: coordinator.async_set_updated_data(
            {"height_mm": height, "locked": client.is_locked}
        )
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "name": name,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: EliotDeskClient = data["client"]
        await client.disconnect()
    return unload_ok
