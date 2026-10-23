"""Binary sensor platform for Cortex STT model load status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import CortexSTTCoordinator
from .entity_setup import async_setup_dynamic_models

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CortexSTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up loaded binary sensors -- one per installed Variant."""
    client = config_entry.runtime_data.client

    update_interval = config_entry.options.get(
        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
    )
    coordinator = CortexSTTCoordinator(hass, client, update_interval=update_interval)
    await coordinator.async_config_entry_first_refresh()

    async_setup_dynamic_models(
        hass,
        config_entry,
        async_add_entities,
        lambda variant: [ModelLoadedSensor(config_entry, coordinator, variant.key)],
    )


class ModelLoadedSensor(CoordinatorEntity[CortexSTTCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether a Variant is currently loaded in memory.

    Polled via the coordinator every 30 seconds by querying GET /api/engine.
    """

    has_entity_name = True
    _attr_translation_key = "model_loaded"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        config_entry: CortexSTTConfigEntry,
        coordinator: CortexSTTCoordinator,
        variant_key: str,
    ) -> None:
        """Initialize the binary sensor.

        Args:
            config_entry: Config entry for this integration instance.
            coordinator: Coordinator that polls engine status.
            variant_key: Key of the Variant to check in loaded_variants.
        """
        super().__init__(coordinator)
        self._variant_key = variant_key
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{variant_key}_loaded"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{variant_key}")},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the Variant is currently loaded."""
        if self.coordinator.data is None:
            return None
        return self._variant_key in self.coordinator.data.loaded_variants
