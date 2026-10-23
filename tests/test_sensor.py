"""Tests for sensor.py -- CortexSTTSensor and update_fn lambdas."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.cortex_stt.models import (
    CortexSTTRuntimeData,
    TranscriptionStats,
    Variant,
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


def _make_variant(
    quant: str | None = "Q8_0", model_id: str = "whisper-small"
) -> Variant:
    """Create an installed Variant with sensible defaults."""
    return Variant(
        model_id=model_id,
        quant=quant,
        model_name="Whisper Small",
        description="",
        languages=["en"],
    )


def _make_sensor(
    variant_key: str = "whisper-small:Q8_0",
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

    sensor = CortexSTTSensor(config_entry, variant_key, desc)
    return sensor, config_entry


# ── Setup entry tests ──


class TestAsyncSetupEntry:
    """Tests for async_setup_entry sensor creation."""

    @pytest.mark.asyncio
    async def test_two_quants_of_one_model_get_separate_sensors(self):
        """Each Variant gets every sensor, and no unique id is shared."""
        variants = [_make_variant("Q4_K_M"), _make_variant("Q8_0")]
        mock_client = AsyncMock()
        runtime_data = CortexSTTRuntimeData(client=mock_client, variants=variants)

        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.runtime_data = runtime_data

        added_entities: list = []
        mock_add_entities = MagicMock(side_effect=lambda e: added_entities.extend(e))

        await async_setup_entry(MagicMock(), config_entry, mock_add_entities)

        unique_ids = [e._attr_unique_id for e in added_entities]
        assert len(set(unique_ids)) == len(unique_ids)
        for variant in variants:
            tracked = {e.variant_key for e in added_entities}
            assert variant.key in tracked

    def test_sensor_unique_id_is_keyed_by_variant(self):
        """The persisted unique id names the Variant and the sensor."""
        sensor, _ = _make_sensor(
            variant_key="whisper-small:Q8_0",
            desc_key="total_requests",
            entry_id="abc123",
        )
        assert (
            sensor._attr_unique_id
            == "cortex_stt_abc123_whisper-small:Q8_0_total_requests"
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
        """Sensor is appended to runtime_data.sensors_by_variant[variant_key] on add."""
        sensor, config_entry = _make_sensor()
        sensor.async_get_last_sensor_data = AsyncMock(return_value=None)

        await sensor.async_added_to_hass()

        channels = config_entry.runtime_data.sensors_by_variant[sensor.variant_key]
        assert sensor in channels

    @pytest.mark.asyncio
    async def test_async_will_remove_from_hass(self):
        """Sensor is removed from runtime_data.sensors_by_variant on removal."""
        sensor, config_entry = _make_sensor()
        config_entry.runtime_data.sensors_by_variant.setdefault(
            sensor.variant_key, []
        ).append(sensor)

        await sensor.async_will_remove_from_hass()

        channels = config_entry.runtime_data.sensors_by_variant[sensor.variant_key]
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

    def test_total_audio_duration_does_not_drift_over_short_clips(self):
        """Many short clips sum to the true total, not a multiple of 0.1 min."""
        fn = _get_desc("total_audio_duration").update_fn
        stats = TranscriptionStats(success=True, api_error=False, audio_seconds=2.5)
        total = None
        for _ in range(100):
            total = fn(total, stats)
        assert total == pytest.approx(250 / 60)

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
