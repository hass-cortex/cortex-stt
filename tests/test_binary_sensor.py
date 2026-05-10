"""Tests for binary_sensor.py -- ModelLoadedSensor."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.cortex_stt.binary_sensor import ModelLoadedSensor
from custom_components.cortex_stt.models import EngineStatus

# ── Helpers ──


def _make_sensor(
    model_id: str = "whisper-small",
    model_name: str = "Whisper Small",
    loaded_models: list[str] | None = None,
    entry_id: str = "test_entry",
) -> tuple[ModelLoadedSensor, MagicMock]:
    """Create a ModelLoadedSensor with mocked coordinator and config entry.

    If loaded_models is None, coordinator.data is set to None (simulating
    no data fetched yet). Otherwise an EngineStatus is created.

    Returns (sensor, coordinator).
    """
    coordinator = MagicMock()
    if loaded_models is None:
        coordinator.data = None
    else:
        coordinator.data = EngineStatus(
            loaded_models=loaded_models,
            loaded_count=len(loaded_models),
        )

    config_entry = MagicMock()
    config_entry.entry_id = entry_id

    sensor = ModelLoadedSensor(config_entry, coordinator, model_id, model_name)
    return sensor, coordinator


# ── Tests ──


class TestModelLoadedSensor:
    """Tests for the ModelLoadedSensor binary sensor."""

    def test_is_on_model_loaded(self):
        """Returns True when model is in loaded_models."""
        sensor, _ = _make_sensor(
            model_id="whisper-small",
            loaded_models=["whisper-small", "whisper-large"],
        )
        assert sensor.is_on is True

    def test_is_on_model_not_loaded(self):
        """Returns False when model is not in loaded_models."""
        sensor, _ = _make_sensor(
            model_id="whisper-small",
            loaded_models=["whisper-large"],
        )
        assert sensor.is_on is False

    def test_is_on_data_none(self):
        """Returns None when coordinator data is None."""
        sensor, _ = _make_sensor(
            model_id="whisper-small",
            loaded_models=None,
        )
        assert sensor.is_on is None

    def test_unique_id_format(self):
        """unique_id follows cortex_stt_{entry_id}_{model_id}_loaded pattern."""
        sensor, _ = _make_sensor(
            model_id="whisper-small",
            entry_id="abc123",
            loaded_models=["whisper-small"],
        )
        assert sensor._attr_unique_id == "cortex_stt_abc123_whisper-small_loaded"

    def test_entity_attributes(self):
        """Verify has_entity_name, translation_key, device_class, entity_category."""
        sensor, _ = _make_sensor(loaded_models=["whisper-small"])

        assert sensor.has_entity_name is True
        assert sensor._attr_translation_key == "model_loaded"
        assert sensor._attr_device_class == "running"
        assert sensor._attr_entity_category == "diagnostic"
