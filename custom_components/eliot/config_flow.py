"""Config flow for Eliot desk integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.components import bluetooth
import voluptuous as vol

from .const import DOMAIN, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class EliotDeskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        # Track devices discovered within this flow instance only
        self._discovered_devices: dict[str, bluetooth.BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ):
        address = discovery_info.address
        _LOGGER.debug("Bluetooth discovery: %s %s", address, discovery_info.name)
        # Deduplicate
        if address in self._discovered_devices:
            return self.async_abort(reason="already_in_progress")
        # Determine if this is an Eliot desk by service UUID or MAC OUI
        service_uuids = [u.lower() for u in discovery_info.service_uuids]

        # Accept only if the full 128-bit service UUID is advertised
        if SERVICE_UUID.lower() not in service_uuids:
            return self.async_abort(reason="not_eliot")

        self._discovered_devices[address] = discovery_info
        await self.async_set_unique_id(address, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        self._addr = address
        suggested_name = discovery_info.name or address

        # Store for use in form
        self._suggested_name = suggested_name

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"address": address, "name": suggested_name},
            data_schema=vol.Schema({vol.Optional("name", default=suggested_name): str}),
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            # Redisplay form with default name to allow user interaction
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "address": self._addr,
                    "name": self._suggested_name,
                },
                data_schema=vol.Schema(
                    {vol.Optional("name", default=self._suggested_name): str}
                ),
            )

        name = user_input.get("name", self._suggested_name)
        return self.async_create_entry(
            title=name, data={"address": self._addr, "name": name}
        )

    # manual flow
    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            data_schema = vol.Schema(
                {
                    vol.Required("address"): selector.TextSelector(),
                    vol.Optional("name"): selector.TextSelector(),
                }
            )
            return self.async_show_form(step_id="user", data_schema=data_schema)
        address = user_input["address"]
        await self.async_set_unique_id(address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=user_input.get("name", address), data=user_input
        )

    @callback
    def async_get_options_flow(self, entry):
        return EliotOptionsFlow(entry)


class EliotOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry):
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Options", data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=config_entries.DataSchema({})
        )
