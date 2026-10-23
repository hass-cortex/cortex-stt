"""Tests for binary_sensor.py -- ModelLoadedSensor."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.cortex_stt.binary_sensor import ModelLoadedSensor
from custom_components.cortex_stt.models import EngineStatus

# ── Helpers ──


def _make_sensor(
    variant_key: str = "whisper-small:Q8_0",
    loaded_variants: set[str] | None = None,
    entry_id: str = "test_entry",
) -> tuple[ModelLoadedSensor, MagicMock]:
    """Create a ModelLoadedSensor with mocked coordinator and config entry.

    If loaded_variants is None, coordinator.data is set to None (simulating
    no data fetched yet). Otherwise an EngineStatus is created.

    Returns (sensor, coordinator).
    """
    coordinator = MagicMock()
    if loaded_variants is None:
        coordinator.data = None
    else:
        coordinator.data = EngineStatus(
            loaded_models=sorted({k.split(":")[0] for k in loaded_variants}),
            loaded_count=len(loaded_variants),
            loaded_variants=loaded_variants,
        )

    config_entry = MagicMock()
    config_entry.entry_id = entry_id

    sensor = ModelLoadedSensor(config_entry, coordinator, variant_key)
    return sensor, coordinator


# ── Tests ──


class TestModelLoadedSensor:
    """Tests for the ModelLoadedSensor binary sensor."""

    def test_is_on_variant_loaded(self):
        """Returns True when this Variant is loaded."""
        sensor, _ = _make_sensor(
            variant_key="whisper-small:Q8_0",
            loaded_variants={"whisper-small:Q8_0", "whisper-large:Q8_0"},
        )
        assert sensor.is_on is True

    def test_another_quant_of_the_model_loaded_is_not_this_one(self):
        """Another quant of the same model being resident does not count."""
        sensor, _ = _make_sensor(
            variant_key="whisper-small:Q8_0",
            loaded_variants={"whisper-small:Q4_K_M"},
        )
        assert sensor.is_on is False

    def test_is_on_data_none(self):
        """Returns None when coordinator data is None."""
        sensor, _ = _make_sensor(loaded_variants=None)
        assert sensor.is_on is None

    def test_unique_id_is_keyed_by_variant(self):
        """The persisted unique id names the Variant, so quants never collide."""
        sensor, _ = _make_sensor(
            variant_key="whisper-small:Q8_0",
            entry_id="abc123",
            loaded_variants=set(),
        )
        assert sensor._attr_unique_id == "cortex_stt_abc123_whisper-small:Q8_0_loaded"

    def test_entity_attributes(self):
        """Verify has_entity_name, translation_key, device_class, entity_category."""
        sensor, _ = _make_sensor(loaded_variants=set())

        assert sensor.has_entity_name is True
        assert sensor._attr_translation_key == "model_loaded"
        assert sensor._attr_device_class == "running"
        assert sensor._attr_entity_category == "diagnostic"
