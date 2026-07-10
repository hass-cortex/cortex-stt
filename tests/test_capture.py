"""Tests for capture-device identification (capture.py)."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.cortex_stt.capture import (
    CAPTURE_CONTEXT_KEY,
    capture_context_var,
    capture_device_from_stream,
    resolve_capture_device,
)


class PipelineRun:
    """Shape-compatible stand-in for assist_pipeline's PipelineRun."""

    def __init__(self, device_id=None, satellite_id=None):
        self._device_id = device_id
        self._satellite_id = satellite_id

    async def _speech_to_text_stream(self):
        yield b"chunk"


def _fake_hass() -> SimpleNamespace:
    return SimpleNamespace(data={})


class TestCaptureDeviceFromStream:
    def test_satellite_id_fallback_without_device(self):
        """A run with only a satellite id returns it verbatim."""
        run = PipelineRun(satellite_id="assist_satellite.kitchen")
        stream = run._speech_to_text_stream()
        assert (
            capture_device_from_stream(_fake_hass(), stream)
            == "assist_satellite.kitchen"
        )

    def test_run_without_ids_returns_none(self):
        run = PipelineRun()
        stream = run._speech_to_text_stream()
        assert capture_device_from_stream(_fake_hass(), stream) is None

    def test_plain_generator_returns_none(self):
        """A generator not bound to a PipelineRun (e.g. a wrapper's replay)."""

        async def replay():
            yield b"chunk"

        assert capture_device_from_stream(_fake_hass(), replay()) is None

    def test_non_generator_stream_returns_none(self):
        assert capture_device_from_stream(_fake_hass(), object()) is None


class TestContextVarRelay:
    def test_var_is_created_once_and_shared(self):
        hass = _fake_hass()
        var1 = capture_context_var(hass)
        var2 = capture_context_var(hass)
        assert var1 is var2
        assert hass.data[CAPTURE_CONTEXT_KEY] is var1

    def test_resolve_falls_back_to_relay_value(self):
        """Wrapper-in-front case: stream introspection fails, relay wins."""
        hass = _fake_hass()
        token = capture_context_var(hass).set("Kitchen Satellite")
        try:

            async def replay():
                yield b"chunk"

            assert resolve_capture_device(hass, replay()) == "Kitchen Satellite"
        finally:
            capture_context_var(hass).reset(token)

    def test_resolve_prefers_direct_introspection(self):
        hass = _fake_hass()
        token = capture_context_var(hass).set("Relayed Value")
        try:
            run = PipelineRun(satellite_id="assist_satellite.direct")
            stream = run._speech_to_text_stream()
            assert resolve_capture_device(hass, stream) == "assist_satellite.direct"
        finally:
            capture_context_var(hass).reset(token)

    def test_resolve_returns_none_when_no_source(self):
        assert resolve_capture_device(_fake_hass(), object()) is None
