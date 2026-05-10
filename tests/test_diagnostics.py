"""Tests for Cortex STT diagnostics platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.cortex_stt.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from custom_components.cortex_stt.models import CortexSTTRuntimeData, ModelInfo


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.data = {"host": "http://server:8769", "api_key": "secret"}
    entry.options = {"update_interval": 45}
    entry.runtime_data = CortexSTTRuntimeData(
        client=MagicMock(),
        models=[
            ModelInfo(
                id="whisper-small",
                name="Whisper Small",
                description="",
                engine_type="whisper",
                status="downloaded",
                size_mb=500,
                supported_languages=["en", "zh"],
            )
        ],
        sensors_by_model={"whisper-small": [MagicMock(), MagicMock()]},
    )
    return entry


@pytest.mark.asyncio
async def test_api_key_is_redacted():
    """The API key must never appear in diagnostics output."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["config_entry"]["data"]["api_key"] != "secret"
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_host_is_preserved():
    """Non-sensitive fields pass through untouched."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["config_entry"]["data"]["host"] == "http://server:8769"


@pytest.mark.asyncio
async def test_options_are_included():
    """Options (including user-configured polling interval) are exposed."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["config_entry"]["options"] == {"update_interval": 45}


@pytest.mark.asyncio
async def test_models_are_dumped_without_private_fields():
    """Discovered models are listed by id and engine_type."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert len(result["models"]) == 1
    model = result["models"][0]
    assert model["id"] == "whisper-small"
    assert model["engine_type"] == "whisper"
    assert model["supported_languages"] == ["en", "zh"]


@pytest.mark.asyncio
async def test_sensor_counts_report_registration():
    """Report how many push channels are registered per model."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["sensor_counts"] == {"whisper-small": 2}


def test_to_redact_covers_api_key():
    """The redaction set must contain the API key field name."""
    assert "api_key" in TO_REDACT
