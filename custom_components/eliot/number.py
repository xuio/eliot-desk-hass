from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Height limits in millimetres (as per desk specs)
MIN_HEIGHT_MM = 634
MAX_HEIGHT_MM = 1289

# Converted limits for UI – centimetres with one decimal
MIN_HEIGHT_CM = MIN_HEIGHT_MM / 10  # 63.4 cm
MAX_HEIGHT_CM = MAX_HEIGHT_MM / 10  # 128.9 cm
STEP_CM = 0.1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    name = data["name"]

    async_add_entities([_EliotDeskTargetHeightNumber(coordinator, client, name)])


class _EliotDeskTargetHeightNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = MIN_HEIGHT_CM
    _attr_native_max_value = MAX_HEIGHT_CM
    _attr_native_step = STEP_CM
    _attr_mode = NumberMode.BOX
    _attr_unit_of_measurement = "cm"

    def __init__(self, coordinator, client, base_name):
        super().__init__(coordinator)
        self._client = client
        self._address = client._address
        self._attr_name = f"{base_name} Target Height"
        self._attr_unique_id = f"{base_name}_target_height"
        # Start with current height (convert to cm) if available
        height_mm = coordinator.data.get("height_mm")
        if height_mm is not None:
            self._attr_native_value = round(height_mm / 10, 1)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._address)},
            "name": self._attr_name.replace(" Target Height", ""),
            "manufacturer": "Eliot",
            "model": "Smart Desk",
        }

    async def async_set_native_value(self, value: float) -> None:
        target_cm = float(value)
        target_mm = int(round(target_cm * 10))
        _LOGGER.debug(
            "Setting desk target height to %.1f cm (%s mm)", target_cm, target_mm
        )
        await self._client.set_height_mm(target_mm)
        self._attr_native_value = round(target_cm, 1)
        # Force coordinator refresh so sensor updates quickly
        await self.coordinator.async_request_refresh()
