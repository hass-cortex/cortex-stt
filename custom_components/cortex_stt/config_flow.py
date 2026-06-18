"""Config flow for Cortex STT integration."""

from __future__ import annotations

import contextlib
import hashlib
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .client import CortexSTTClient
from .const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
    }
)


class CortexSTTConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Cortex STT."""

    VERSION = 1

    _hassio_discovery: HassioServiceInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return CortexSTTOptionsFlow()

    async def _validate_input(
        self, host: str, api_key: str
    ) -> tuple[str | None, CortexSTTClient]:
        """Validate host and API key, return (error, client)."""
        session = async_get_clientsession(self.hass)
        client = CortexSTTClient(host=host, api_key=api_key, session=session)
        error = await client.validate()
        return error, client

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step.

        Collects host URL and API key, validates by checking health
        (connectivity) and engine endpoint (auth).
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            error, client = await self._validate_input(
                user_input[CONF_HOST], user_input[CONF_API_KEY]
            )
            if error:
                errors["base"] = error
            else:
                # Prevent duplicate entries for the same server
                unique_id = hashlib.sha256(user_input[CONF_HOST].encode()).hexdigest()[
                    :16
                ]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Use server version in title if available
                title = "Cortex STT"
                with contextlib.suppress(aiohttp.ClientError, TimeoutError, KeyError):
                    health = await client.health()
                    title = f"Cortex STT ({health.get('version', '')})"

                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle Supervisor discovery.

        Payload (addon-provided): { host, port, api_key }. A new payload with
        the same uuid but a different api_key (admin rotated it in the addon's
        options) auto-updates the stored credentials — no manual reauth.
        """
        _LOGGER.debug("Supervisor discovery info: %s", discovery_info)

        host = f"http://{discovery_info.config['host']}:{discovery_info.config['port']}"
        api_key = discovery_info.config["api_key"]

        # Adopt entries whose host matches — their unique_id is hash-of-host,
        # not the Supervisor UUID, so the fast path below would miss them.
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_HOST) == host:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: host, CONF_API_KEY: api_key},
                    unique_id=discovery_info.uuid,
                    reason="already_configured",
                )

        await self.async_set_unique_id(discovery_info.uuid)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host, CONF_API_KEY: api_key}
        )

        self._hassio_discovery = discovery_info
        self.context.update(
            {
                "title_placeholders": {"name": discovery_info.name},
                "configuration_url": (
                    f"homeassistant://hassio/addon/{discovery_info.slug}/info"
                ),
            }
        )
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm Supervisor discovery and create the entry."""
        assert self._hassio_discovery is not None
        discovery = self._hassio_discovery
        errors: dict[str, str] = {}

        if user_input is not None:
            host = f"http://{discovery.config['host']}:{discovery.config['port']}"
            api_key = discovery.config["api_key"]

            error, client = await self._validate_input(host, api_key)
            if error:
                errors["base"] = error
            else:
                title = discovery.name
                with contextlib.suppress(aiohttp.ClientError, TimeoutError, KeyError):
                    health = await client.health()
                    if version := health.get("version"):
                        title = f"{discovery.name} ({version})"

                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": discovery.name},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauth when API key becomes invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation with new API key."""
        errors: dict[str, str] = {}

        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            error, _ = await self._validate_input(
                reauth_entry.data[CONF_HOST], user_input[CONF_API_KEY]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
        )


class CortexSTTOptionsFlow(OptionsFlowWithReload):
    """Options flow for Cortex STT."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage user-configurable options (polling interval)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
