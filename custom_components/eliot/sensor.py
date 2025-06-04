"""Sensor providing current desk height in mm."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    name = data["name"]

    async_add_entities([_EliotDeskHeightSensor(coordinator, client, name)])


class _EliotDeskHeightSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, client, base_name):
        super().__init__(coordinator)
        self._address = client._address
        self._attr_name = f"{base_name} Height"
        self._attr_unique_id = f"{base_name}_height"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._address)},
            "name": self._attr_name.replace(" Height", ""),
            "manufacturer": "Eliot",
            "model": "Smart Desk",
        }

    @property
    def native_value(self):
        height_mm = self.coordinator.data.get("height_mm")
        if height_mm is None:
            return None
        return round(height_mm / 10, 1)
