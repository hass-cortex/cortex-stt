"""Sensor platform for Cortex STT runtime statistics."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity_setup import async_setup_dynamic_models
from .models import CortexSTTRuntimeData, TranscriptionStats

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CortexSTTSensorDescription(SensorEntityDescription):
    """Describe a Cortex STT sensor."""

    update_fn: Callable[[Any, TranscriptionStats], Any] = lambda cur, s: cur


SENSOR_DESCRIPTIONS: tuple[CortexSTTSensorDescription, ...] = (
    CortexSTTSensorDescription(
        key="total_requests",
        translation_key="total_requests",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        update_fn=lambda cur, s: int(cur or 0) + 1,
    ),
    CortexSTTSensorDescription(
        key="successful_requests",
        translation_key="successful_requests",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        update_fn=lambda cur, s: int(cur or 0) + (1 if s.success else 0),
    ),
    CortexSTTSensorDescription(
        key="failed_requests",
        translation_key="failed_requests",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        update_fn=lambda cur, s: int(cur or 0) + (1 if s.api_error else 0),
    ),
    CortexSTTSensorDescription(
        key="last_duration",
        translation_key="last_duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        update_fn=lambda cur, s: round(s.duration_ms, 1) if s.success else cur,
    ),
    CortexSTTSensorDescription(
        key="average_duration",
        translation_key="average_duration",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        update_fn=lambda cur, s: (
            round(s.avg_duration_ms, 1) if s.success and s.avg_duration_ms else cur
        ),
    ),
    CortexSTTSensorDescription(
        key="last_audio_size",
        translation_key="last_audio_size",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        update_fn=lambda cur, s: s.audio_bytes if s.success else cur,
    ),
    CortexSTTSensorDescription(
        key="total_audio_duration",
        translation_key="total_audio_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        update_fn=lambda cur, s: (
            round(float(cur or 0) + s.audio_seconds / 60, 1)
            if s.success
            else (cur or 0)
        ),
    ),
    CortexSTTSensorDescription(
        key="last_audio_duration",
        translation_key="last_audio_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        update_fn=lambda cur, s: round(s.audio_seconds, 1) if s.success else cur,
    ),
    CortexSTTSensorDescription(
        key="last_raw_text",
        translation_key="last_raw_text",
        update_fn=lambda cur, s: (
            s.raw_text if s.success else (None if not s.api_error else cur)
        ),
    ),
    CortexSTTSensorDescription(
        key="last_result",
        translation_key="last_result",
        entity_category=EntityCategory.DIAGNOSTIC,
        options=["success", "no_speech", "api_error"],
        device_class=SensorDeviceClass.ENUM,
        update_fn=lambda cur, s: (
            "success" if s.success else ("api_error" if s.api_error else "no_speech")
        ),
    ),
    CortexSTTSensorDescription(
        key="rtf",
        translation_key="rtf",
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        update_fn=lambda cur, s: (
            round(s.rtf, 3) if s.success and s.rtf is not None else cur
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CortexSTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Cortex STT sensors -- 11 per downloaded model."""
    async_setup_dynamic_models(
        hass,
        config_entry,
        async_add_entities,
        lambda model: [
            CortexSTTSensor(config_entry, model.id, model.name, desc)
            for desc in SENSOR_DESCRIPTIONS
        ],
    )


class CortexSTTSensor(RestoreSensor):
    """Sensor that tracks per-model Cortex STT statistics.

    Each sensor owns its value and persists it via RestoreSensor.
    The STT entity pushes TranscriptionStats after each API call,
    and each sensor updates itself via its description's update_fn.
    """

    has_entity_name = True
    entity_description: CortexSTTSensorDescription
    _attr_should_poll = False

    def __init__(
        self,
        config_entry: CortexSTTConfigEntry,
        model_id: str,
        model_name: str,
        description: CortexSTTSensorDescription,
    ) -> None:
        """Initialize the sensor.

        Args:
            config_entry: Config entry for this integration instance.
            model_id: Model ID this sensor tracks.
            model_name: Human-readable model name.
            description: Sensor entity description with update_fn.
        """
        self.entity_description = description
        self._config_entry = config_entry
        self._model_id = model_id
        self._attr_unique_id = (
            f"{DOMAIN}_{config_entry.entry_id}_{model_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{model_id}")},
        )

    @property
    def model_id(self) -> str:
        """Return the model ID this sensor tracks."""
        return self._model_id

    async def async_added_to_hass(self) -> None:
        """Restore last state and register for push updates from STT entity."""
        await super().async_added_to_hass()

        # Restore previous value from HA's built-in state restore
        last_data = await self.async_get_last_sensor_data()
        if last_data and last_data.native_value is not None:
            self._attr_native_value = last_data.native_value

        # Register for push updates from STT entity
        runtime_data: CortexSTTRuntimeData = self._config_entry.runtime_data
        runtime_data.sensors_by_model.setdefault(self._model_id, []).append(self)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister this sensor from push updates."""
        runtime_data: CortexSTTRuntimeData = self._config_entry.runtime_data
        channels = runtime_data.sensors_by_model.get(self._model_id)
        if channels is not None:
            with contextlib.suppress(ValueError):
                channels.remove(self)

    def handle_transcription(self, stats: TranscriptionStats) -> None:
        """Update sensor value from transcription statistics."""
        new_value = self.entity_description.update_fn(self._attr_native_value, stats)
        if new_value != self._attr_native_value:
            self._attr_native_value = new_value
            self.async_write_ha_state()
