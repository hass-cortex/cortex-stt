"""Tests for sensor.py -- CortexSTTSensor and update_fn lambdas."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.cortex_stt.models import (
    CortexSTTRuntimeData,
    ModelInfo,
    TranscriptionStats,
)
from custom_components.cortex_stt.sensor import (
    SENSOR_DESCRIPTIONS,
    CortexSTTSensor,
    CortexSTTSensorDescription,
    async_setup_entry,
)

# ── Helpers ──


def _get_desc(key: str) -> CortexSTTSensorDescription:
    """Find a sensor description by key."""
    return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)


def _make_model(**overrides) -> ModelInfo:
    """Create a ModelInfo with sensible defaults."""
    defaults = {
        "id": "whisper-small",
        "name": "Whisper Small",
        "description": "",
        "engine_type": "whisper",
        "status": "downloaded",
        "size_mb": 500,
        "supported_languages": ["en"],
    }
    defaults.update(overrides)
    return ModelInfo(**defaults)


def _make_sensor(
    model_id: str = "whisper-small",
    model_name: str = "Whisper Small",
    desc_key: str = "total_requests",
    entry_id: str = "test_entry",
) -> tuple[CortexSTTSensor, MagicMock]:
    """Create a CortexSTTSensor with mocked config entry.

    Returns (sensor, mock_config_entry).
    """
    desc = _get_desc(desc_key)
    mock_client = AsyncMock()
    runtime_data = CortexSTTRuntimeData(client=mock_client)

    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.runtime_data = runtime_data

    sensor = CortexSTTSensor(config_entry, model_id, model_name, desc)
    return sensor, config_entry


# ── Setup entry tests ──


class TestAsyncSetupEntry:
    """Tests for async_setup_entry sensor creation."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_sensors(self):
        """2 models x 11 descriptions = 22 sensor entities."""
        models = [
            _make_model(id="whisper-small", name="Whisper Small"),
            _make_model(id="whisper-large", name="Whisper Large"),
        ]
        mock_client = AsyncMock()
        runtime_data = CortexSTTRuntimeData(client=mock_client, models=models)

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.runtime_data = runtime_data

        added_entities: list = []
        mock_add_entities = MagicMock(side_effect=lambda e: added_entities.extend(e))

        await async_setup_entry(MagicMock(), config_entry, mock_add_entities)

        assert len(added_entities) == 2 * len(SENSOR_DESCRIPTIONS)
        assert len(added_entities) == 22

    def test_sensor_unique_id_format(self):
        """unique_id follows cortex_stt_{entry_id}_{model_id}_{key} pattern."""
        sensor, _ = _make_sensor(
            model_id="whisper-small",
            desc_key="total_requests",
            entry_id="abc123",
        )
        assert (
            sensor._attr_unique_id == "cortex_stt_abc123_whisper-small_total_requests"
        )


# ── RestoreSensor lifecycle tests ──


class TestSensorLifecycle:
    """Tests for RestoreSensor lifecycle methods."""

    @pytest.mark.asyncio
    async def test_async_added_to_hass_restore(self):
        """Restores value when async_get_last_sensor_data returns data."""
        sensor, _ = _make_sensor()

        last_data = MagicMock()
        last_data.native_value = 42
        sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value == 42

    @pytest.mark.asyncio
    async def test_async_added_to_hass_no_restore(self):
        """Value stays None when no previous data to restore."""
        sensor, _ = _make_sensor()

        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)
        sensor._attr_native_value = None

        await sensor.async_added_to_hass()

        assert sensor._attr_native_value is None

    @pytest.mark.asyncio
    async def test_async_added_to_hass_registers_sensor(self):
        """Sensor is appended to runtime_data.sensors_by_model[model_id] on add."""
        sensor, config_entry = _make_sensor()
        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        channels = config_entry.runtime_data.sensors_by_model[sensor.model_id]
        assert sensor in channels

    @pytest.mark.asyncio
    async def test_async_will_remove_from_hass(self):
        """Sensor is removed from runtime_data.sensors_by_model on removal."""
        sensor, config_entry = _make_sensor()
        config_entry.runtime_data.sensors_by_model.setdefault(
            sensor.model_id, []
        ).append(sensor)

        await sensor.async_will_remove_from_hass()

        channels = config_entry.runtime_data.sensors_by_model[sensor.model_id]
        assert sensor not in channels


# ── handle_transcription tests ──


class TestHandleTranscription:
    """Tests for CortexSTTSensor.handle_transcription."""

    def test_handle_transcription_updates_value(self):
        """State update is written when value changes."""
        sensor, _ = _make_sensor(desc_key="total_requests")
        sensor._attr_native_value = None
        sensor.async_write_ha_state = MagicMock()

        stats = TranscriptionStats(success=True, api_error=False)
        sensor.handle_transcription(stats)

        assert sensor._attr_native_value == 1
        sensor.async_write_ha_state.assert_called_once()

    def test_handle_transcription_no_change(self):
        """State update is NOT written when value is unchanged."""
        sensor, _ = _make_sensor(desc_key="last_duration")
        sensor._attr_native_value = None
        sensor.async_write_ha_state = MagicMock()

        # Failed transcription: last_duration keeps current (None)
        stats = TranscriptionStats(success=False, api_error=True, duration_ms=100)
        sensor.handle_transcription(stats)

        sensor.async_write_ha_state.assert_not_called()


# ── update_fn tests for each sensor description ──


class TestUpdateFunctions:
    """Tests for all 11 SENSOR_DESCRIPTIONS update_fn lambdas."""

    def test_total_requests_increments(self):
        """total_requests always increments by 1."""
        fn = _get_desc("total_requests").update_fn
        assert fn(None, TranscriptionStats(success=True, api_error=False)) == 1
        assert fn(5, TranscriptionStats(success=False, api_error=True)) == 6

    def test_successful_requests_increments_on_success(self):
        """successful_requests increments only on success."""
        fn = _get_desc("successful_requests").update_fn
        assert fn(None, TranscriptionStats(success=True, api_error=False)) == 1
        assert fn(3, TranscriptionStats(success=True, api_error=False)) == 4
        assert fn(3, TranscriptionStats(success=False, api_error=False)) == 3

    def test_failed_requests_increments_on_api_error(self):
        """failed_requests increments only on api_error."""
        fn = _get_desc("failed_requests").update_fn
        assert fn(None, TranscriptionStats(success=False, api_error=True)) == 1
        assert fn(2, TranscriptionStats(success=False, api_error=True)) == 3
        assert fn(2, TranscriptionStats(success=False, api_error=False)) == 2

    def test_last_duration_updates_on_success(self):
        """last_duration updates with duration_ms on success, keeps current otherwise."""
        fn = _get_desc("last_duration").update_fn
        stats_ok = TranscriptionStats(
            success=True, api_error=False, duration_ms=123.456
        )
        assert fn(None, stats_ok) == 123.5

        stats_fail = TranscriptionStats(success=False, api_error=True, duration_ms=200)
        assert fn(100.0, stats_fail) == 100.0

    def test_average_duration_updates(self):
        """average_duration updates with avg_duration_ms on success when present."""
        fn = _get_desc("average_duration").update_fn

        stats_with_avg = TranscriptionStats(
            success=True, api_error=False, avg_duration_ms=150.789
        )
        assert fn(None, stats_with_avg) == 150.8

        # success=True but avg_duration_ms is None -> keeps current
        stats_no_avg = TranscriptionStats(
            success=True, api_error=False, avg_duration_ms=None
        )
        assert fn(100.0, stats_no_avg) == 100.0

        # success=False -> keeps current
        stats_fail = TranscriptionStats(
            success=False, api_error=False, avg_duration_ms=200.0
        )
        assert fn(100.0, stats_fail) == 100.0

    def test_last_audio_size_updates_on_success(self):
        """last_audio_size returns audio_bytes on success."""
        fn = _get_desc("last_audio_size").update_fn
        stats_ok = TranscriptionStats(success=True, api_error=False, audio_bytes=32000)
        assert fn(None, stats_ok) == 32000

        stats_fail = TranscriptionStats(
            success=False, api_error=True, audio_bytes=32000
        )
        assert fn(16000, stats_fail) == 16000

    def test_total_audio_duration_accumulates(self):
        """total_audio_duration accumulates minutes on success."""
        fn = _get_desc("total_audio_duration").update_fn

        # 60 seconds = 1 minute
        stats_ok = TranscriptionStats(success=True, api_error=False, audio_seconds=60.0)
        assert fn(None, stats_ok) == 1.0
        assert fn(2.0, stats_ok) == 3.0

        # Failed: keeps current
        stats_fail = TranscriptionStats(
            success=False, api_error=True, audio_seconds=120.0
        )
        assert fn(5.0, stats_fail) == 5.0

        # Failed with None current returns 0
        assert fn(None, stats_fail) == 0

    def test_last_audio_duration_updates(self):
        """last_audio_duration returns seconds on success."""
        fn = _get_desc("last_audio_duration").update_fn

        stats_ok = TranscriptionStats(
            success=True, api_error=False, audio_seconds=3.456
        )
        assert fn(None, stats_ok) == 3.5

        stats_fail = TranscriptionStats(
            success=False, api_error=False, audio_seconds=5.0
        )
        assert fn(2.0, stats_fail) == 2.0

    def test_last_raw_text_success(self):
        """last_raw_text returns text on success."""
        fn = _get_desc("last_raw_text").update_fn
        stats = TranscriptionStats(
            success=True, api_error=False, raw_text="hello world"
        )
        assert fn(None, stats) == "hello world"

    def test_last_raw_text_clears_on_no_speech(self):
        """last_raw_text returns None when not api_error and not success (no speech)."""
        fn = _get_desc("last_raw_text").update_fn
        stats = TranscriptionStats(success=False, api_error=False)
        assert fn("previous text", stats) is None

    def test_last_raw_text_keeps_on_api_error(self):
        """last_raw_text keeps current value on api_error."""
        fn = _get_desc("last_raw_text").update_fn
        stats = TranscriptionStats(success=False, api_error=True)
        assert fn("previous text", stats) == "previous text"

    def test_last_result_enum(self):
        """last_result returns correct enum string for each outcome."""
        fn = _get_desc("last_result").update_fn

        assert fn(None, TranscriptionStats(success=True, api_error=False)) == "success"
        assert (
            fn(None, TranscriptionStats(success=False, api_error=True)) == "api_error"
        )
        assert (
            fn(None, TranscriptionStats(success=False, api_error=False)) == "no_speech"
        )

    def test_rtf_updates_on_success(self):
        """rtf updates with rounded value on success when rtf is present."""
        fn = _get_desc("rtf").update_fn

        stats_ok = TranscriptionStats(success=True, api_error=False, rtf=0.12345)
        assert fn(None, stats_ok) == 0.123

        # success but rtf is None -> keeps current
        stats_no_rtf = TranscriptionStats(success=True, api_error=False, rtf=None)
        assert fn(0.5, stats_no_rtf) == 0.5

        # failure -> keeps current
        stats_fail = TranscriptionStats(success=False, api_error=True, rtf=0.2)
        assert fn(0.5, stats_fail) == 0.5
