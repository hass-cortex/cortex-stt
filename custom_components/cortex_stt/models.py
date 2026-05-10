"""Data models for Cortex STT integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .client import CortexSTTClient


@dataclass
class ModelInfo:
    """A model from the Cortex STT API."""

    id: str
    name: str
    description: str
    engine_type: str
    status: str
    size_mb: int
    supported_languages: list[str]
    is_loaded: bool = False
    is_recommended: bool = False


@dataclass
class EngineStatus:
    """Engine status from GET /api/engine."""

    loaded_models: list[str]
    loaded_count: int


@dataclass
class TranscribeResult:
    """Response from POST /api/transcribe."""

    text: str
    model: str
    duration_ms: int
    inference_ms: int
    segments: list[dict]


@dataclass
class TranscriptionStats:
    """Statistics emitted after each transcription attempt."""

    success: bool
    api_error: bool
    duration_ms: float = 0.0
    audio_bytes: int = 0
    audio_seconds: float = 0.0
    language: str = ""
    raw_text: str | None = None
    avg_duration_ms: float | None = None
    rtf: float | None = None


class SensorPushChannel(Protocol):
    """Anything that accepts transcription stats for a single model."""

    def handle_transcription(self, stats: TranscriptionStats) -> None: ...


@dataclass
class CortexSTTRuntimeData:
    """Runtime data shared between entities."""

    client: CortexSTTClient
    models: list[ModelInfo] = field(default_factory=list)
    sensors_by_model: dict[str, list[SensorPushChannel]] = field(default_factory=dict)
