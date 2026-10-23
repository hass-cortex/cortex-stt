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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .client import CortexSTTAppTooOldError, CortexSTTClient
from .const import (
    CONF_API_KEY,
    CONF_HOST,
    DOMAIN,
    EVENT_MODELS_CHANGED,
    models_changed_signal,
)
from .migration import async_migrate_to_variants
from .models import CortexSTTRuntimeData, installed_variants

type CortexSTTConfigEntry = ConfigEntry[CortexSTTRuntimeData]

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = ["stt", "sensor", "binary_sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ISSUE_APP_TOO_OLD: Final = "app_too_old"


def _entity_suffixes() -> list[str]:
    """Return what follows the Variant key in each entity's unique id."""
    from .sensor import SENSOR_DESCRIPTIONS  # noqa: PLC0415 -- platform module

    return ["", "_loaded", *(f"_{d.key}" for d in SENSOR_DESCRIPTIONS)]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Cortex STT integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CortexSTTConfigEntry) -> bool:
    """Set up Cortex STT from a config entry.

    Steps:
    1. Validate connectivity and auth
    2. Discover installed Variants via GET /api/models, and move pre-Variant
       devices and entities onto them
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

    # Discover installed Variants
    try:
        all_models = await client.list_models()
    except CortexSTTAppTooOldError as err:
        # Retried until the app is updated; the repair says why it waits.
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_APP_TOO_OLD,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_APP_TOO_OLD,
        )
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key=ISSUE_APP_TOO_OLD,
        ) from err
    except Exception as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="list_models_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    ir.async_delete_issue(hass, DOMAIN, ISSUE_APP_TOO_OLD)

    variants = installed_variants(all_models)
    _LOGGER.info(
        "Discovered %d installed variants of %d models",
        len(variants),
        len(all_models),
    )

    # Before any entity registers: move pre-Variant devices and entities onto
    # the Variant each model was serving, so their entity ids survive.
    async_migrate_to_variants(hass, entry, all_models, _entity_suffixes())

    entry.runtime_data = CortexSTTRuntimeData(client=client, variants=variants)

    # Remove devices for Variants no longer on the server
    _remove_stale_devices(hass, entry, {v.key for v in variants})

    # Listen for the addon's "models changed" event so entities appear/disappear
    # live without a config-entry reload. The addon fires this on the HA event
    # bus via the Supervisor proxy; the payload is advisory (we reconcile the
    # full set). Registered BEFORE forwarding platforms so an event fired during
    # the setup window still updates runtime_data.models (which the platforms
    # then build from) instead of being dropped.
    async def _handle_models_changed(event: Event) -> None:
        """Reconcile entities when the addon's installed Variants change.

        Re-fetch the authoritative list, drop devices for removed Variants,
        then signal platforms to add new ones. Duplicate/out-of-order events
        are harmless (every event triggers a full reconcile); a lost event is
        corrected by the next event or a config-entry reload.
        """
        try:
            all_models = await client.list_models()
        except (
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            KeyError,
            CortexSTTAppTooOldError,
        ) as err:
            # ValueError/KeyError guard against a malformed /api/models body so
            # a bad response never escapes the event-bus callback as a traceback.
            _LOGGER.warning("models-changed event but model refresh failed: %s", err)
            return
        variants = installed_variants(all_models)
        entry.runtime_data.variants = variants
        _remove_stale_devices(hass, entry, {v.key for v in variants})
        async_dispatcher_send(hass, models_changed_signal(entry.entry_id), variants)

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
    current_keys: set[str],
) -> None:
    """Remove devices for Variants that are no longer installed on the server."""
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        for _, identifier in device.identifiers:
            if identifier.startswith(f"{entry.entry_id}_"):
                key = identifier.removeprefix(f"{entry.entry_id}_")
                if key not in current_keys:
                    _LOGGER.info("Removing stale device for variant %s", key)
                    device_reg.async_remove_device(device.id)
                break
