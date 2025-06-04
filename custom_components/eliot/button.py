"""Button entities to control Eliot desk movement."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BUTTONS = {
    "up": ("Move Up", "mdi:arrow-up"),
    "down": ("Move Down", "mdi:arrow-down"),
    "stop": ("Stop", "mdi:stop"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    name = data["name"]

    entities: list[ButtonEntity] = []
    for key, (label, icon) in BUTTONS.items():
        entities.append(_EliotDeskButton(coordinator, client, name, key, label, icon))

    async_add_entities(entities)


class _EliotDeskButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, client, base_name, key, label, icon):
        super().__init__(coordinator)
        self._client = client
        self._key = key
        self._attr_name = f"{base_name} {label}"
        self._attr_unique_id = f"{base_name}_{key}"
        self._attr_icon = icon
        self._address = client._address  # for device info

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._address)},
            "name": self._attr_name.rsplit(" ", 1)[0],
            "manufacturer": "Eliot",
            "model": "Smart Desk",
        }

    async def async_press(self) -> None:
        if self._key == "up":
            await self._client.move_up()
        elif self._key == "down":
            await self._client.move_down()
        elif self._key == "stop":
            await self._client.stop()
