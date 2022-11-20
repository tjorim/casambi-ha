"""Config flow for Casambi Bluetooth integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from CasambiBt import Casambi, discover
from CasambiBt.errors import AuthenticationError, BluetoothError, NetworkNotFoundError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import CONF_IMPORT_GROUPS, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = hass.helpers.httpx_client.get_async_client()
    casa = Casambi(client)
    await casa.connect(data[CONF_ADDRESS], data[CONF_PASSWORD])

    # Return info that you want to store in the config entry.
    return {"title": casa.networkName, "id": casa.networkId}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Casambi Bluetooth."""

    discover_task: asyncio.Task | None = None

    VERSION = 1

    async def _async_discover(self) -> Iterable[str] | None:  # TODO: Check return type
        result: Iterable[str] | None = None
        try:
            result = await discover()  # Takes some time to complete.
        finally:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
            )

        return result

    async def _async_create_casa_entry(
        self, title: str, id: str, data: dict[str, Any]
    ) -> FlowResult:
        existing_entry = await self.async_set_unique_id(id)

        if existing_entry:
            changed = self.hass.config_entries.async_update_entry(
                existing_entry, unique_id=id, title=title, data=data
            )

            if not changed:
                return self.async_abort(reason="already_configured")

            self.hass.async_create_task(
                self.hass.config_entries.async_reload(existing_entry.entry_id)
            )
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title=title, data=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step. We search for networks here."""
        if not self.discover_task:
            self.discover_task = self.hass.async_create_task(self._async_discover())
            return self.async_show_progress(step_id="user", progress_action="discover")

        try:
            self.addrs = await self.discover_task
        except BluetoothError:
            return self.async_show_progress_done(next_step_id="bluetooth_error")

        return self.async_show_progress_done(next_step_id="network")

    async def async_step_bluetooth_error(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle bluetooth errors.

        The config flow can't proceed if there is a bluetooth error so this is the last step.
        """
        return self.async_abort(reason="bluetooth_error")

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entry of network information and attempt to connect."""
        if not len(self.addrs):
            self.addrs.append(None)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=self.addrs[0]): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_IMPORT_GROUPS, default=True): cv.boolean,
            }
        )

        if user_input:
            errors = {}

            try:
                info = await _validate_input(self.hass, user_input)
            except NetworkNotFoundError:
                errors["base"] = "cannot_connect"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return await self._async_create_casa_entry(
                    info["title"], info["id"], user_input
                )

            return self.async_show_form(
                step_id="user", data_schema=data_schema, errors=errors
            )

        return self.async_show_form(step_id="network", data_schema=data_schema)
