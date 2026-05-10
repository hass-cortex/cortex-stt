"""Tests for stt.py -- CortexSTTEntity and _expand_languages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.cortex_stt.models import (
    CortexSTTRuntimeData,
    ModelInfo,
    TranscribeResult,
    TranscriptionStats,
)
from custom_components.cortex_stt.stt import CortexSTTEntity, _expand_languages

# ── Helpers ──


def _make_model(**overrides) -> ModelInfo:
    """Create a ModelInfo with sensible defaults."""
    defaults = {
        "id": "whisper-small",
        "name": "Whisper Small",
        "description": "",
        "engine_type": "whisper",
        "status": "downloaded",
        "size_mb": 500,
        "supported_languages": ["en", "zh"],
    }
    defaults.update(overrides)
    return ModelInfo(**defaults)


def _make_entity(
    model: ModelInfo | None = None,
    entry_id: str = "test_entry",
) -> tuple[CortexSTTEntity, AsyncMock, MagicMock]:
    """Create a CortexSTTEntity with mocked dependencies.

    Returns (entity, mock_client, mock_config_entry).
    """
    if model is None:
        model = _make_model()

    mock_client = AsyncMock()
    runtime_data = CortexSTTRuntimeData(client=mock_client, models=[model])

    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.runtime_data = runtime_data

    entity = CortexSTTEntity(config_entry, mock_client, model)
    return entity, mock_client, config_entry


async def _make_stream(chunks: list[bytes]):
    """Create an async iterable of audio chunks."""
    for chunk in chunks:
        yield chunk


def _make_metadata(language: str = "en") -> MagicMock:
    """Create a mock SpeechMetadata."""
    metadata = MagicMock()
    metadata.language = language
    return metadata


# ── _expand_languages tests ──


class TestExpandLanguages:
    """Tests for the _expand_languages helper function."""

    def test_expand_basic_code(self):
        """'en' expands to base + all locale variants."""
        result = _expand_languages(["en"])
        assert result == ["en", "en-US", "en-GB", "en-AU", "en-IN"]

    def test_expand_unknown_code(self):
        """Unknown code stays as-is with no expansion."""
        result = _expand_languages(["xx"])
        assert result == ["xx"]

    def test_expand_multiple_codes(self):
        """Multiple codes each expand independently."""
        result = _expand_languages(["zh", "en"])
        assert result == [
            "zh",
            "zh-TW",
            "zh-CN",
            "zh-HK",
            "zh-Hans",
            "zh-Hant",
            "en",
            "en-US",
            "en-GB",
            "en-AU",
            "en-IN",
        ]

    def test_expand_empty(self):
        """Empty list returns empty list."""
        result = _expand_languages([])
        assert result == []


# ── CortexSTTEntity property tests ──


class TestCortexSTTEntityProperties:
    """Tests for CortexSTTEntity property accessors."""

    def test_supported_languages(self):
        """supported_languages uses _expand_languages on model languages."""
        model = _make_model(supported_languages=["en", "zh"])
        entity, _, _ = _make_entity(model=model)

        langs = entity.supported_languages
        # Should contain base codes plus all variants
        assert "en" in langs
        assert "en-US" in langs
        assert "zh" in langs
        assert "zh-TW" in langs

    def test_supported_formats(self):
        """supported_formats returns [WAV]."""
        entity, _, _ = _make_entity()
        assert entity.supported_formats == ["wav"]

    def test_supported_codecs(self):
        """supported_codecs returns [PCM]."""
        entity, _, _ = _make_entity()
        assert entity.supported_codecs == ["pcm"]

    def test_unique_id_format(self):
        """unique_id follows cortex_stt_{entry_id}_{model_id} pattern."""
        model = _make_model(id="whisper-small")
        entity, _, _ = _make_entity(model=model, entry_id="abc123")
        assert entity._attr_unique_id == "cortex_stt_abc123_whisper-small"

    def test_device_info(self):
        """device_info contains correct identifiers and metadata."""
        model = _make_model(id="whisper-small", name="Whisper Small")
        entity, _, _ = _make_entity(model=model, entry_id="abc123")

        info = entity._attr_device_info
        assert ("cortex_stt", "abc123_whisper-small") in info["identifiers"]
        assert info["name"] == "Whisper Small"
        assert info["manufacturer"] == "cortex-stt"
        assert info["model"] == "whisper-small"
        assert info["entry_type"] == "service"


# ── async_process_audio_stream tests ──


class TestAsyncProcessAudioStream:
    """Tests for CortexSTTEntity.async_process_audio_stream."""

    @pytest.mark.asyncio
    async def test_empty_audio_stream(self):
        """Empty audio stream returns ERROR result."""
        entity, _, _ = _make_entity()
        metadata = _make_metadata()

        result = await entity.async_process_audio_stream(metadata, _make_stream([]))

        assert result.result == "error"
        assert result.text is None

    @pytest.mark.asyncio
    async def test_transcription_success(self):
        """Successful transcription returns SUCCESS with text."""
        entity, mock_client, _ = _make_entity()
        metadata = _make_metadata(language="en")

        mock_client.transcribe.return_value = TranscribeResult(
            text="hello world",
            model="whisper-small",
            duration_ms=100,
            inference_ms=80,
            segments=[],
        )

        result = await entity.async_process_audio_stream(
            metadata, _make_stream([b"\x00" * 32000])
        )

        assert result.result == "success"
        assert result.text == "hello world"
        mock_client.transcribe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transcription_api_error(self):
        """API exception returns ERROR and pushes stats with api_error=True."""
        entity, mock_client, _ = _make_entity()
        metadata = _make_metadata()

        mock_client.transcribe.side_effect = aiohttp.ClientError("connection refused")

        pushed_stats: list[TranscriptionStats] = []
        entity._push_stats = lambda s: pushed_stats.append(s)

        result = await entity.async_process_audio_stream(
            metadata, _make_stream([b"\x00" * 1000])
        )

        assert result.result == "error"
        assert result.text is None
        assert len(pushed_stats) == 1
        assert pushed_stats[0].api_error is True
        assert pushed_stats[0].success is False

    @pytest.mark.asyncio
    async def test_transcription_no_speech(self):
        """Empty transcription text returns ERROR with api_error=False."""
        entity, mock_client, _ = _make_entity()
        metadata = _make_metadata()

        mock_client.transcribe.return_value = TranscribeResult(
            text="",
            model="whisper-small",
            duration_ms=50,
            inference_ms=40,
            segments=[],
        )

        pushed_stats: list[TranscriptionStats] = []
        entity._push_stats = lambda s: pushed_stats.append(s)

        result = await entity.async_process_audio_stream(
            metadata, _make_stream([b"\x00" * 1000])
        )

        assert result.result == "error"
        assert result.text is None
        assert len(pushed_stats) == 1
        assert pushed_stats[0].api_error is False
        assert pushed_stats[0].success is False

    @pytest.mark.asyncio
    async def test_push_stats_to_sensors(self):
        """_push_stats calls handle_transcription on sensors matching model_id."""
        model = _make_model(id="whisper-small")
        entity, mock_client, config_entry = _make_entity(model=model)

        # Create mock sensors: one matching, one not
        matching_sensor = MagicMock()
        matching_sensor.model_id = "whisper-small"

        other_sensor = MagicMock()
        other_sensor.model_id = "whisper-large"

        config_entry.runtime_data.sensors_by_model = {
            "whisper-small": [matching_sensor],
            "whisper-large": [other_sensor],
        }

        stats = TranscriptionStats(success=True, api_error=False)
        entity._push_stats(stats)

        matching_sensor.handle_transcription.assert_called_once_with(stats)
        other_sensor.handle_transcription.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_average_calculation(self):
        """Two successful transcriptions yield correct avg_duration_ms in stats."""
        entity, mock_client, _ = _make_entity()
        metadata = _make_metadata()

        pushed_stats: list[TranscriptionStats] = []
        entity._push_stats = lambda s: pushed_stats.append(s)

        # First transcription
        mock_client.transcribe.return_value = TranscribeResult(
            text="first",
            model="whisper-small",
            duration_ms=100,
            inference_ms=80,
            segments=[],
        )
        await entity.async_process_audio_stream(
            metadata, _make_stream([b"\x00" * 32000])
        )

        # Second transcription
        mock_client.transcribe.return_value = TranscribeResult(
            text="second",
            model="whisper-small",
            duration_ms=200,
            inference_ms=160,
            segments=[],
        )
        await entity.async_process_audio_stream(
            metadata, _make_stream([b"\x00" * 32000])
        )

        assert len(pushed_stats) == 2
        assert pushed_stats[0].success is True
        assert pushed_stats[1].success is True

        # Both should have avg_duration_ms set
        assert pushed_stats[0].avg_duration_ms is not None
        assert pushed_stats[1].avg_duration_ms is not None

        # Session count should be 2 after second call
        assert entity._session_success_count == 2
