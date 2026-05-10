"""Tests for CortexSTTCoordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.cortex_stt.coordinator import CortexSTTCoordinator
from custom_components.cortex_stt.models import EngineStatus


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.engine_status = AsyncMock()
    return client


@pytest.fixture
def coordinator(mock_hass, mock_client):
    return CortexSTTCoordinator(hass=mock_hass, client=mock_client)


async def test_update_success(coordinator, mock_client):
    """Successful _async_update_data returns EngineStatus as coordinator.data."""
    expected = EngineStatus(loaded_models=["whisper-large-v3"], loaded_count=1)
    mock_client.engine_status.return_value = expected

    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data == expected
    mock_client.engine_status.assert_awaited_once()


async def test_update_error_raises_update_failed(coordinator, mock_client):
    """_async_update_data wraps exceptions in UpdateFailed with translation key."""
    mock_client.engine_status.side_effect = OSError("connection refused")

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator.async_config_entry_first_refresh()
    assert exc_info.value.translation_key == "engine_status_failed"
    assert exc_info.value.translation_placeholders == {"error": "connection refused"}


def test_update_interval_is_30_seconds(coordinator):
    """Coordinator polls every 30 seconds."""
    assert coordinator.update_interval == timedelta(seconds=30)
