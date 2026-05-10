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
    models = [
        {
            "id": m.id,
            "name": m.name,
            "engine_type": m.engine_type,
            "status": m.status,
            "size_mb": m.size_mb,
            "supported_languages": m.supported_languages,
            "is_loaded": m.is_loaded,
            "is_recommended": m.is_recommended,
        }
        for m in runtime_data.models
    ]

    return {
        "config_entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "models": models,
        "sensor_counts": {
            model_id: len(channels)
            for model_id, channels in runtime_data.sensors_by_model.items()
        },
    }
