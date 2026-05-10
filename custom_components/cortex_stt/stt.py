"""STT platform for Cortex STT -- one entity per downloaded model."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import CortexSTTClient
from .const import DOMAIN
from .models import CortexSTTRuntimeData, ModelInfo, TranscriptionStats

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# PCM audio: 16kHz sample rate, 16-bit (2 bytes), mono (1 channel)
_PCM_BYTES_PER_SECOND = 16000 * 2 * 1

# Common BCP-47 locale variants for base language codes.
# HA pipelines use locales like "zh-TW", but our server uses base codes "zh".
_LOCALE_VARIANTS: dict[str, list[str]] = {
    "zh": ["zh-TW", "zh-CN", "zh-HK", "zh-Hans", "zh-Hant"],
    "en": ["en-US", "en-GB", "en-AU", "en-IN"],
    "es": ["es-ES", "es-MX", "es-AR"],
    "fr": ["fr-FR", "fr-CA"],
    "pt": ["pt-BR", "pt-PT"],
    "ar": ["ar-SA", "ar-EG"],
    "de": ["de-DE", "de-AT"],
    "ja": ["ja-JP"],
    "ko": ["ko-KR"],
    "ru": ["ru-RU"],
    "it": ["it-IT"],
    "nl": ["nl-NL"],
    "pl": ["pl-PL"],
    "tr": ["tr-TR"],
    "vi": ["vi-VN"],
    "th": ["th-TH"],
    "uk": ["uk-UA"],
    "hi": ["hi-IN"],
    "he": ["he-IL"],
    "yue": ["yue-Hant-HK"],
}


def _expand_languages(base_codes: list[str]) -> list[str]:
    """Expand base language codes to include common locale variants."""
    result: list[str] = []
    for code in base_codes:
        result.append(code)
        if code in _LOCALE_VARIANTS:
            result.extend(_LOCALE_VARIANTS[code])
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CortexSTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Cortex STT entities -- one per downloaded model."""
    runtime_data = config_entry.runtime_data
    client: CortexSTTClient = runtime_data.client

    entities = [
        CortexSTTEntity(config_entry, client, model) for model in runtime_data.models
    ]
    async_add_entities(entities)


class CortexSTTEntity(SpeechToTextEntity):
    """Per-model STT entity backed by Cortex STT."""

    has_entity_name = True

    def __init__(
        self,
        config_entry: CortexSTTConfigEntry,
        client: CortexSTTClient,
        model: ModelInfo,
    ) -> None:
        """Initialize the STT entity.

        Args:
            config_entry: Config entry with server credentials.
            client: HTTP client for Cortex STT.
            model: Model info for this entity.
        """
        self._config_entry = config_entry
        self._client = client
        self._model = model
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{model.id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{model.id}")},
            name=model.name,
            manufacturer="cortex-stt",
            model=model.id,
            entry_type=DeviceEntryType.SERVICE,
        )

        # Session-level counters for average duration (ephemeral)
        self._session_total_duration_ms: float = 0.0
        self._session_success_count: int = 0

    @property
    def supported_languages(self) -> list[str]:
        """Return languages supported by this model.

        Expands base language codes (e.g. 'zh') to include common BCP-47
        locale variants (e.g. 'zh-TW', 'zh-CN') so HA pipeline matching works.
        """
        return _expand_languages(self._model.supported_languages)

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return supported audio formats."""
        return [AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return supported audio codecs."""
        return [AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return supported bit rates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return supported sample rates."""
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return supported audio channels."""
        return [AudioChannels.CHANNEL_MONO]

    def _push_stats(self, stats: TranscriptionStats) -> None:
        """Push transcription statistics to sensors for this model."""
        runtime_data: CortexSTTRuntimeData = self._config_entry.runtime_data
        for channel in runtime_data.sensors_by_model.get(self._model.id, ()):
            channel.handle_transcription(stats)

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Process an audio stream and return transcribed text.

        Args:
            metadata: Audio metadata (format, codec, sample rate, etc.).
            stream: Async iterable of audio byte chunks.

        Returns:
            SpeechResult with transcribed text or error.
        """
        # Collect audio bytes
        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        audio_data = b"".join(chunks)

        if not audio_data:
            _LOGGER.warning("Received empty audio stream for model %s", self._model.id)
            return SpeechResult(text=None, result=SpeechResultState.ERROR)

        _LOGGER.debug(
            "Audio received: %d bytes, model=%s, language=%s",
            len(audio_data),
            self._model.id,
            metadata.language,
        )

        audio_seconds = len(audio_data) / _PCM_BYTES_PER_SECOND
        t0 = time.monotonic()

        try:
            result = await self._client.transcribe(
                audio_data, self._model.id, metadata.language
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Transcription failed for model %s: %s", self._model.id, err)
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._push_stats(
                TranscriptionStats(
                    success=False,
                    api_error=True,
                    duration_ms=elapsed_ms,
                    audio_bytes=len(audio_data),
                    audio_seconds=audio_seconds,
                    language=metadata.language,
                )
            )
            return SpeechResult(text=None, result=SpeechResultState.ERROR)

        elapsed_ms = (time.monotonic() - t0) * 1000

        if not result.text:
            _LOGGER.debug("No speech recognized by model %s", self._model.id)
            self._push_stats(
                TranscriptionStats(
                    success=False,
                    api_error=False,
                    duration_ms=elapsed_ms,
                    audio_bytes=len(audio_data),
                    audio_seconds=audio_seconds,
                    language=metadata.language,
                )
            )
            return SpeechResult(text=None, result=SpeechResultState.ERROR)

        _LOGGER.info("Cortex STT [%s] result: %s", self._model.id, result.text)

        # Update session averages
        self._session_success_count += 1
        self._session_total_duration_ms += elapsed_ms
        avg_ms = self._session_total_duration_ms / self._session_success_count

        # Compute real-time factor (inference time / audio duration)
        rtf = result.inference_ms / (audio_seconds * 1000) if audio_seconds > 0 else 0

        self._push_stats(
            TranscriptionStats(
                success=True,
                api_error=False,
                duration_ms=elapsed_ms,
                audio_bytes=len(audio_data),
                audio_seconds=audio_seconds,
                language=metadata.language,
                raw_text=result.text,
                avg_duration_ms=avg_ms,
                rtf=rtf,
            )
        )

        return SpeechResult(text=result.text, result=SpeechResultState.SUCCESS)
