"""Constants for Cortex STT integration."""

from __future__ import annotations

DOMAIN = "cortex_stt"

CONF_HOST = "host"
CONF_API_KEY = "api_key"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 3600
