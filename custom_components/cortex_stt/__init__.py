"""Cortex STT integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import CortexSTTClient
from .const import CONF_API_KEY, CONF_HOST, DOMAIN
from .models import CortexSTTRuntimeData

type CortexSTTConfigEntry = ConfigEntry[CortexSTTRuntimeData]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = ["stt", "sensor", "binary_sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Cortex STT integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CortexSTTConfigEntry) -> bool:
    """Set up Cortex STT from a config entry.

    Steps:
    1. Validate connectivity and auth
    2. Discover downloaded models via GET /api/models
    3. Store client and runtime data
    4. Forward platform setups (stt, sensor, binary_sensor)
    """
    session = async_get_clientsession(hass)
    client = CortexSTTClient(
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
        session=session,
    )

    # Validate connectivity and auth
    error = await client.validate()
    if error == "invalid_api_key":
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_api_key",
        )
    if error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": error},
        )

    # Discover downloaded models
    try:
        all_models = await client.list_models()
    except Exception as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="list_models_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    downloaded = [m for m in all_models if m.status == "downloaded"]
    _LOGGER.info(
        "Discovered %d downloaded models (of %d total)",
        len(downloaded),
        len(all_models),
    )

    entry.runtime_data = CortexSTTRuntimeData(client=client, models=downloaded)

    # Remove devices for models no longer on server
    current_model_ids = {m.id for m in downloaded}
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        for _, identifier in device.identifiers:
            if identifier.startswith(f"{entry.entry_id}_"):
                model_id = identifier.removeprefix(f"{entry.entry_id}_")
                if model_id not in current_model_ids:
                    _LOGGER.info("Removing stale device for model %s", model_id)
                    device_reg.async_remove_device(device.id)
                break

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: CortexSTTConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CortexSTTConfigEntry) -> bool:
    """Unload a Cortex STT config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
