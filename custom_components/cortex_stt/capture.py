"""Capture-device identification for STT quality analysis.

Identifies which Assist satellite / voice device recorded the audio a
transcription request carries, so the Cortex STT server can persist it
(``capture_device`` on the history record) for per-microphone quality
analysis.

Two sources, tried in order:

1. **Stream introspection** — the assist_pipeline passes its
   ``PipelineRun._speech_to_text_stream`` bound async generator as the
   STT audio stream; its frame locals hold the run, which knows the
   triggering device. Deterministic under concurrent runs (object
   identity, not timing). Works when the pipeline calls this entity
   directly.
2. **Shared ContextVar relay** — when a wrapper entity (stt-corrector)
   sits at the chain head, it consumes the original stream and forwards
   a replay generator, breaking (1). The wrapper does the introspection
   itself and publishes the result in a ``ContextVar`` shared through
   ``hass.data[CAPTURE_CONTEXT_KEY]``; contextvars propagate within the
   pipeline's asyncio task, so the value is visible here and isolated
   from concurrent runs.

Both sources are best-effort: they touch assist_pipeline internals, so
any shape mismatch degrades to ``None`` (record saved without a capture
device) and logs at debug level — transcription is never affected.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

# Shared-contract key: stt-corrector sets the ContextVar stored under this
# hass.data key; cortex_stt reads it. Both components must use the same
# literal (each vendors its own copy of this module).
CAPTURE_CONTEXT_KEY = "stt_capture_device_context"


def capture_context_var(hass: HomeAssistant) -> ContextVar[str | None]:
    """Return the shared capture-device ContextVar, creating it once."""
    var: ContextVar[str | None] | None = hass.data.get(CAPTURE_CONTEXT_KEY)
    if var is None:
        var = ContextVar("stt_capture_device", default=None)
        hass.data[CAPTURE_CONTEXT_KEY] = var
    return var


def capture_device_from_stream(hass: HomeAssistant, stream: Any) -> str | None:
    """Best-effort: name the assist satellite that recorded ``stream``.

    Returns a human-readable device name (device registry ``name_by_user``
    / ``name``), falling back to the satellite entity id or raw device id.
    ``None`` when the stream is not a recognizable PipelineRun generator.
    """
    try:
        frame = getattr(stream, "ag_frame", None)
        if frame is None:
            return None
        run = frame.f_locals.get("self")
        if type(run).__name__ != "PipelineRun":
            return None
        device_id: str | None = getattr(run, "_device_id", None)
        satellite_id: str | None = getattr(run, "_satellite_id", None)
    except Exception:  # noqa: BLE001 — introspection must never break STT
        _LOGGER.debug("capture-device introspection failed", exc_info=True)
        return None

    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        if device:
            return device.name_by_user or device.name or device_id
        return device_id
    if satellite_id:
        return satellite_id
    return None


def resolve_capture_device(hass: HomeAssistant, stream: Any) -> str | None:
    """Introspect ``stream`` first; fall back to the ContextVar relay."""
    direct = capture_device_from_stream(hass, stream)
    if direct is not None:
        return direct
    relayed = capture_context_var(hass).get()
    if relayed is None:
        _LOGGER.debug(
            "no capture device: stream not a PipelineRun generator and no relay value"
        )
    return relayed
