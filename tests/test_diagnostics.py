"""Tests for Cortex STT diagnostics platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.cortex_stt.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from custom_components.cortex_stt.models import CortexSTTRuntimeData, Variant


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.data = {"host": "http://server:8769", "api_key": "secret"}
    entry.options = {"update_interval": 45}
    entry.runtime_data = CortexSTTRuntimeData(
        client=MagicMock(),
        variants=[
            Variant(
                model_id="whisper-small",
                quant="Q8_0",
                model_name="Whisper Small",
                description="",
                languages=["en", "zh"],
                size_mb=500,
            )
        ],
        sensors_by_variant={"whisper-small:Q8_0": [MagicMock(), MagicMock()]},
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
async def test_variants_are_listed_with_their_quant():
    """Discovered Variants are listed by key, model, quant and languages."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    variant = result["variants"][0]
    assert variant["key"] == "whisper-small:Q8_0"
    assert variant["quant"] == "Q8_0"
    assert variant["languages"] == ["en", "zh"]


@pytest.mark.asyncio
async def test_sensor_counts_report_registration():
    """Report how many push channels are registered per Variant."""
    entry = _make_entry()
    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert result["sensor_counts"] == {"whisper-small:Q8_0": 2}


def test_to_redact_covers_api_key():
    """The redaction set must contain the API key field name."""
    assert "api_key" in TO_REDACT
