"""Cortex STT integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .client import CortexSTTClient
from .const import (
    CONF_API_KEY,
    CONF_HOST,
    DOMAIN,
    EVENT_MODELS_CHANGED,
    models_changed_signal,
)
from .models import CortexSTTRuntimeData, ModelInfo

type CortexSTTConfigEntry = ConfigEntry[CortexSTTRuntimeData]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = ["stt", "sensor", "binary_sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _downloaded_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """Return only models that are downloaded and thus entity-worthy.

    Single source of truth for the readiness filter, shared by setup-time
    discovery and the live event reconcile so they can never disagree.
    """
    return [m for m in models if m.status == "downloaded"]


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

    downloaded = _downloaded_models(all_models)
    _LOGGER.info(
        "Discovered %d downloaded models (of %d total)",
        len(downloaded),
        len(all_models),
    )

    entry.runtime_data = CortexSTTRuntimeData(client=client, models=downloaded)

    # Remove devices for models no longer on server
    _remove_stale_devices(hass, entry, {m.id for m in downloaded})

    # Listen for the addon's "models changed" event so entities appear/disappear
    # live without a config-entry reload. The addon fires this on the HA event
    # bus via the Supervisor proxy; the payload is advisory (we reconcile the
    # full set). Registered BEFORE forwarding platforms so an event fired during
    # the setup window still updates runtime_data.models (which the platforms
    # then build from) instead of being dropped.
    async def _handle_models_changed(event: Event) -> None:
        """Reconcile entities when the addon's downloaded-model set changes.

        Re-fetch the authoritative list, drop devices for removed models, then
        signal platforms to add new ones. Duplicate/out-of-order events are
        harmless (every event triggers a full reconcile); a lost event is
        corrected by the next event or a config-entry reload.
        """
        try:
            all_models = await client.list_models()
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as err:
            # ValueError/KeyError guard against a malformed /api/models body so
            # a bad response never escapes the event-bus callback as a traceback.
            _LOGGER.warning("models-changed event but model refresh failed: %s", err)
            return
        models = _downloaded_models(all_models)
        entry.runtime_data.models = models
        _remove_stale_devices(hass, entry, {m.id for m in models})
        async_dispatcher_send(hass, models_changed_signal(entry.entry_id), models)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_MODELS_CHANGED, _handle_models_changed)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: CortexSTTConfigEntry) -> bool:
    """Unload a Cortex STT config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _remove_stale_devices(
    hass: HomeAssistant,
    entry: CortexSTTConfigEntry,
    current_model_ids: set[str],
) -> None:
    """Remove devices for models that are no longer downloaded on the server."""
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        for _, identifier in device.identifiers:
            if identifier.startswith(f"{entry.entry_id}_"):
                model_id = identifier.removeprefix(f"{entry.entry_id}_")
                if model_id not in current_model_ids:
                    _LOGGER.info("Removing stale device for model %s", model_id)
                    device_reg.async_remove_device(device.id)
                break
