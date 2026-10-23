"""Data models for Cortex STT integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .client import CortexSTTClient


@dataclass
class VariantInfo:
    """One quant of a model, as GET /api/models reports it."""

    quant: str | None
    status: str
    size_mb: int = 0
    is_loaded: bool = False


@dataclass
class ModelInfo:
    """A model from the Cortex STT API."""

    id: str
    name: str
    description: str
    status: str
    size_mb: int
    languages: list[str]
    is_loaded: bool = False
    recommended: bool = False
    preferred_quant: str | None = None
    variants: list[VariantInfo] = field(default_factory=list)


def variant_key(model_id: str, quant: str | None) -> str:
    """Return the app's key for a Variant: ``model:quant``, or a Custom model's id."""
    return f"{model_id}:{quant}" if quant else model_id


@dataclass
class Variant:
    """One installed model at one quant -- the unit Home Assistant sees.

    Each Variant is its own device with its own STT entity, so two
    pipelines can use two quants of one model at once.
    """

    model_id: str
    quant: str | None
    model_name: str
    description: str
    languages: list[str]
    size_mb: int = 0

    @property
    def key(self) -> str:
        """Return the identity shared by the device and its entities."""
        return variant_key(self.model_id, self.quant)

    @property
    def name(self) -> str:
        """Return the device name: the model, with its quant when it has one.

        Always carries the quant, so installing a second quant never
        renames the first.
        """
        return f"{self.model_name} ({self.quant})" if self.quant else self.model_name


def installed_variants(models: list[ModelInfo]) -> list[Variant]:
    """Return every installed Variant across ``models``."""
    return [
        Variant(
            model_id=m.id,
            quant=v.quant,
            model_name=m.name,
            description=m.description,
            languages=m.languages,
            size_mb=v.size_mb,
        )
        for m in models
        for v in m.variants
        if v.status == "downloaded"
    ]


@dataclass
class EngineStatus:
    """Engine status from GET /api/engine."""

    loaded_models: list[str]
    loaded_count: int
    loaded_variants: set[str] = field(default_factory=set)
    """Keys of the loaded Variants."""


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
    """Anything that accepts transcription stats for a single Variant."""

    def handle_transcription(self, stats: TranscriptionStats) -> None: ...


@dataclass
class CortexSTTRuntimeData:
    """Runtime data shared between entities."""

    client: CortexSTTClient
    variants: list[Variant] = field(default_factory=list)
    sensors_by_variant: dict[str, list[SensorPushChannel]] = field(default_factory=dict)
    """Sensor channels keyed by Variant key."""
