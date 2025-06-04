from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    name = data["name"]

    async_add_entities([_EliotDeskControlSwitch(coordinator, client, name)])


class _EliotDeskControlSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, client, base_name):
        super().__init__(coordinator)
        self._client = client
        self._address = client._address
        self._attr_name = f"{base_name} Disable Physical Controls"
        self._attr_unique_id = f"{base_name}_disable_controls"
        self._attr_icon = "mdi:lock"

    # ------------------------------------------------------------------
    @property
    def is_on(self) -> bool | None:
        """Return True if physical controls are disabled (desk locked)."""
        return self.coordinator.data.get("locked")

    async def async_turn_on(self, **kwargs):
        await self._client.lock()

    async def async_turn_off(self, **kwargs):
        await self._client.unlock()

    # ------------------------------------------------------------------
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._address)},
            "name": self._attr_name.replace(" Disable Physical Controls", ""),
            "manufacturer": "Eliot",
            "model": "Smart Desk",
        }
