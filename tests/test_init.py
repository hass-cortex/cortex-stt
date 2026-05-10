"""Tests for Cortex STT __init__.py (setup/unload)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.device_registry as dr
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.cortex_stt import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.cortex_stt.models import CortexSTTRuntimeData, ModelInfo


def _make_model(model_id: str, status: str = "downloaded") -> ModelInfo:
    """Create a ModelInfo for testing."""
    return ModelInfo(
        id=model_id,
        name=model_id,
        description="test model",
        engine_type="whisper",
        status=status,
        size_mb=100,
        supported_languages=["en"],
    )


# ── async_setup ──


@pytest.mark.asyncio
async def test_async_setup_returns_true(mock_hass):
    """async_setup always returns True."""
    result = await async_setup(mock_hass, {})
    assert result is True


# ── async_setup_entry ──


@pytest.mark.asyncio
async def test_setup_entry_success(mock_hass, mock_config_entry):
    """Set up entry with valid client and models."""
    models = [_make_model("whisper-tiny"), _make_model("parakeet-0.6b")]
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(return_value=models)

    mock_device_reg = MagicMock()
    dr.async_get = MagicMock(return_value=mock_device_reg)
    dr.async_entries_for_config_entry = MagicMock(return_value=[])

    with (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
    ):
        result = await async_setup_entry(mock_hass, mock_config_entry)

    assert result is True
    assert isinstance(mock_config_entry.runtime_data, CortexSTTRuntimeData)
    assert mock_config_entry.runtime_data.client is mock_client
    assert len(mock_config_entry.runtime_data.models) == 2
    mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
        mock_config_entry, ["stt", "sensor", "binary_sensor"]
    )


@pytest.mark.asyncio
async def test_setup_entry_invalid_api_key(mock_hass, mock_config_entry):
    """Raise ConfigEntryAuthFailed when API key is invalid."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value="invalid_api_key")

    with (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
        pytest.raises(ConfigEntryAuthFailed) as exc_info,
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
    assert exc_info.value.translation_key == "invalid_api_key"


@pytest.mark.asyncio
async def test_setup_entry_cannot_connect(mock_hass, mock_config_entry):
    """Raise ConfigEntryNotReady when server is unreachable."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value="cannot_connect")

    with (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
        pytest.raises(ConfigEntryNotReady) as exc_info,
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
    assert exc_info.value.translation_key == "cannot_connect"
    assert exc_info.value.translation_placeholders == {"error": "cannot_connect"}


@pytest.mark.asyncio
async def test_setup_entry_list_models_error(mock_hass, mock_config_entry):
    """Raise ConfigEntryNotReady when list_models fails."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
        pytest.raises(ConfigEntryNotReady) as exc_info,
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
    assert exc_info.value.translation_key == "list_models_failed"
    assert exc_info.value.translation_placeholders == {"error": "connection refused"}


@pytest.mark.asyncio
async def test_setup_entry_stale_device_removal(mock_hass, mock_config_entry):
    """Remove devices for models no longer on the server."""
    # Server only has whisper-tiny now; old-model was removed
    models = [_make_model("whisper-tiny")]
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(return_value=models)

    # Simulate a stale device for "old-model"
    stale_device = MagicMock()
    stale_device.id = "device_stale"
    stale_device.identifiers = {("cortex_stt", "test_entry_123_old-model")}

    # Current device that should NOT be removed
    current_device = MagicMock()
    current_device.id = "device_current"
    current_device.identifiers = {("cortex_stt", "test_entry_123_whisper-tiny")}

    mock_device_reg = MagicMock()
    dr.async_get = MagicMock(return_value=mock_device_reg)
    dr.async_entries_for_config_entry = MagicMock(
        return_value=[stale_device, current_device]
    )

    with (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
    ):
        result = await async_setup_entry(mock_hass, mock_config_entry)

    assert result is True
    # Stale device removed, current device kept
    mock_device_reg.async_remove_device.assert_called_once_with("device_stale")


# ── async_unload_entry ──


@pytest.mark.asyncio
async def test_unload_entry(mock_hass, mock_config_entry):
    """Verify async_unload_platforms is called."""
    result = await async_unload_entry(mock_hass, mock_config_entry)
    assert result is True
    mock_hass.config_entries.async_unload_platforms.assert_called_once_with(
        mock_config_entry, ["stt", "sensor", "binary_sensor"]
    )
