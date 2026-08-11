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

from .capture import resolve_capture_device
from .client import (
    CortexSTTClient,
    CortexSTTStreamConnectError,
)
from .const import DOMAIN
from .entity_setup import async_setup_dynamic_models
from .models import CortexSTTRuntimeData, ModelInfo, TranscriptionStats

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# PCM audio: 16kHz sample rate, 16-bit (2 bytes), mono (1 channel)
_PCM_BYTES_PER_SECOND = 16000 * 2 * 1

# Common BCP-47 locale variants for base language codes.
# Not about being selectable — HA's language_util.matches() already scores
# "zh-TW" against a bare "zh". It decides WHICH tag wins: matches() returns a
# tag from the list below and the pipeline copies it into metadata.language,
# so advertising the variants is what preserves the region for anything
# downstream that keys on locale. The addon takes either granularity.
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
    client: CortexSTTClient = config_entry.runtime_data.client

    async_setup_dynamic_models(
        hass,
        config_entry,
        async_add_entities,
        lambda model: [CortexSTTEntity(config_entry, client, model)],
    )


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
        return _expand_languages(self._model.languages)

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

    def _empty_result(self) -> SpeechResult:
        """Log and return the ERROR result for an empty audio stream."""
        _LOGGER.warning("Received empty audio stream for model %s", self._model.id)
        return SpeechResult(text=None, result=SpeechResultState.ERROR)

    def _api_error_result(
        self, err: Exception, byte_count: int, language: str, elapsed_ms: float
    ) -> SpeechResult:
        """Push api-error stats and return the ERROR result."""
        _LOGGER.error("Transcription failed for model %s: %s", self._model.id, err)
        self._push_stats(
            TranscriptionStats(
                success=False,
                api_error=True,
                duration_ms=elapsed_ms,
                audio_bytes=byte_count,
                audio_seconds=byte_count / _PCM_BYTES_PER_SECOND,
                language=language,
            )
        )
        return SpeechResult(text=None, result=SpeechResultState.ERROR)

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Process an audio stream and return transcribed text.

        Pre-reads to the first non-empty chunk so a silent utterance (a common
        false wake-word) never opens a server session. Then feeds audio to the
        server over the WebSocket streaming endpoint as chunks arrive; if the WS
        handshake fails, falls back once to buffering and using the sync POST
        endpoint.

        Args:
            metadata: Audio metadata (format, codec, sample rate, etc.).
            stream: Async iterable of audio byte chunks.

        Returns:
            SpeechResult with transcribed text or error.
        """
        # Identify the capture device BEFORE touching the stream — once the
        # generator is exhausted its frame (and the PipelineRun reference
        # inside it) is gone. Best-effort: None simply omits the field.
        # (`hass` is unset when the entity hasn't been added to HA, e.g.
        # in unit tests.)
        hass = getattr(self, "hass", None)
        capture_device = resolve_capture_device(hass, stream) if hass else None

        # Pre-read until the first non-empty chunk. An empty stream must resolve
        # locally (no server contact: no engine slot, no zero-sample finalize,
        # no history row).
        stream_iter = aiter(stream)
        first_chunk = b""
        while True:
            try:
                chunk = await anext(stream_iter)
            except StopAsyncIteration:
                break
            if chunk:
                first_chunk = chunk
                break
        if not first_chunk:
            return self._empty_result()

        byte_count = 0

        async def _tracked_stream() -> AsyncIterable[bytes]:
            nonlocal byte_count
            byte_count += len(first_chunk)
            yield first_chunk
            async for chunk in stream_iter:
                byte_count += len(chunk)
                yield chunk

        tracked = _tracked_stream()
        t0 = time.monotonic()

        try:
            result = await self._client.transcribe_stream(
                tracked, self._model.id, metadata.language, capture_device
            )
        except CortexSTTStreamConnectError as err:
            _LOGGER.warning(
                "WS stream unavailable for model %s, falling back to POST: %s",
                self._model.id,
                err,
            )
            # Handshake failed before any chunk was fed: drain the still-fresh
            # tracked stream (first chunk + remainder) and POST once.
            chunks: list[bytes] = []
            async for chunk in tracked:
                chunks.append(chunk)
            try:
                result = await self._client.transcribe(
                    b"".join(chunks), self._model.id, metadata.language, capture_device
                )
            except (aiohttp.ClientError, TimeoutError) as err2:
                return self._api_error_result(
                    err2, byte_count, metadata.language, (time.monotonic() - t0) * 1000
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            return self._api_error_result(
                err, byte_count, metadata.language, (time.monotonic() - t0) * 1000
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        audio_seconds = byte_count / _PCM_BYTES_PER_SECOND

        _LOGGER.debug(
            "Audio received: %d bytes, model=%s, language=%s",
            byte_count,
            self._model.id,
            metadata.language,
        )

        if not result.text:
            _LOGGER.debug("No speech recognized by model %s", self._model.id)
            self._push_stats(
                TranscriptionStats(
                    success=False,
                    api_error=False,
                    duration_ms=elapsed_ms,
                    audio_bytes=byte_count,
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
                audio_bytes=byte_count,
                audio_seconds=audio_seconds,
                language=metadata.language,
                raw_text=result.text,
                avg_duration_ms=avg_ms,
                rtf=rtf,
            )
        )

        return SpeechResult(text=result.text, result=SpeechResultState.SUCCESS)
