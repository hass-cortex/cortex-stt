"""Constants for Cortex STT integration."""

from __future__ import annotations

DOMAIN = "cortex_stt"

CONF_HOST = "host"
CONF_API_KEY = "api_key"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 3600

# HA event the addon fires (via the Supervisor proxy) when its downloaded-model
# set changes; the integration listens to add/remove entities without a reload.
EVENT_MODELS_CHANGED = "cortex_stt_models_changed"


def models_changed_signal(entry_id: str) -> str:
    """Return the dispatcher signal fired when the model set changes.

    Sent by the event-bus handler after the addon fires a models-changed event;
    each platform listens to add entities for newly-discovered models.
    """
    return f"{DOMAIN}_models_changed_{entry_id}"
