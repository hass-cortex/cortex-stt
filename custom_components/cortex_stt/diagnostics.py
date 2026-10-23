"""Diagnostics support for Cortex STT."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CortexSTTConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = entry.runtime_data
    variants = [
        {
            "key": v.key,
            "model_id": v.model_id,
            "quant": v.quant,
            "name": v.name,
            "size_mb": v.size_mb,
            "languages": v.languages,
        }
        for v in runtime_data.variants
    ]

    return {
        "config_entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "variants": variants,
        "sensor_counts": {
            key: len(channels)
            for key, channels in runtime_data.sensors_by_variant.items()
        },
    }
