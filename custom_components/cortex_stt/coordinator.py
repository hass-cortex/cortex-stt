"""DataUpdateCoordinator for Cortex STT engine status polling."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CortexSTTClient
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .models import EngineStatus

_LOGGER = logging.getLogger(__name__)


class CortexSTTCoordinator(DataUpdateCoordinator[EngineStatus]):
    """Poll Cortex STT /api/engine at a configurable interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: CortexSTTClient,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            client: HTTP client for Cortex STT.
            update_interval: Polling interval in seconds.
        """
        super().__init__(
            hass,
            _LOGGER,
            name="cortex_stt_engine",
            update_interval=timedelta(seconds=update_interval),
        )
        self._client = client

    async def _async_update_data(self) -> EngineStatus:
        """Fetch engine status from Cortex STT."""
        try:
            return await self._client.engine_status()
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="engine_status_failed",
                translation_placeholders={"error": str(err)},
            ) from err
