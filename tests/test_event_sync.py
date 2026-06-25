"""Tests for event-driven live model add/remove.

Covers the ``__init__`` event-bus reconcile handler (re-fetch, drop stale
devices, signal platforms) and the per-platform dynamic-add path (add only new
models, re-add after a delete via the pruned known-set).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.device_registry as dr
import pytest
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from custom_components.cortex_stt import async_setup_entry
from custom_components.cortex_stt.const import (
    EVENT_MODELS_CHANGED,
    models_changed_signal,
)
from custom_components.cortex_stt.models import CortexSTTRuntimeData, ModelInfo
from custom_components.cortex_stt.stt import async_setup_entry as stt_setup_entry


def _make_model(model_id: str, status: str = "downloaded") -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        description="test model",
        engine_type="whisper",
        status=status,
        size_mb=100,
        supported_languages=["en"],
    )


def _patched_setup(mock_client):
    return (
        patch(
            "custom_components.cortex_stt.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.cortex_stt.CortexSTTClient",
            return_value=mock_client,
        ),
    )


async def _setup_and_get_handler(mock_hass, mock_config_entry, mock_client):
    """Run setup and return the registered models-changed event handler."""
    dr.async_get = MagicMock(return_value=MagicMock())
    dr.async_entries_for_config_entry = MagicMock(return_value=[])
    p1, p2 = _patched_setup(mock_client)
    with p1, p2:
        await async_setup_entry(mock_hass, mock_config_entry)
    # async_setup_entry registers exactly one bus listener for our event type.
    call = mock_hass.bus.async_listen.call_args
    assert call.args[0] == EVENT_MODELS_CHANGED
    return call.args[1]


# ── __init__ event-bus handler ──


@pytest.mark.asyncio
async def test_setup_registers_event_listener(mock_hass, mock_config_entry):
    """Setup subscribes to the event and wires the unsubscribe to unload."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(return_value=[_make_model("whisper-tiny")])

    handler = await _setup_and_get_handler(mock_hass, mock_config_entry, mock_client)
    assert callable(handler)
    # The bus-listener unsub must be registered for cleanup on unload, so the
    # listener cannot leak across reloads.
    mock_config_entry.async_on_unload.assert_any_call(
        mock_hass.bus.async_listen.return_value
    )


@pytest.mark.asyncio
async def test_event_handler_adds_and_signals(mock_hass, mock_config_entry):
    """An event re-fetches models, updates runtime_data, and dispatches."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(return_value=[_make_model("whisper-tiny")])

    received: list[list[ModelInfo]] = []
    async_dispatcher_connect(
        mock_hass,
        models_changed_signal(mock_config_entry.entry_id),
        received.append,
    )

    handler = await _setup_and_get_handler(mock_hass, mock_config_entry, mock_client)

    # Addon now reports a second downloaded model (plus an undownloaded one).
    mock_client.list_models = AsyncMock(
        return_value=[
            _make_model("whisper-tiny"),
            _make_model("parakeet-0.6b"),
            _make_model("sensevoice", status="available"),
        ]
    )
    await handler(MagicMock())

    assert received, "dispatcher signal was not sent"
    assert {m.id for m in received[-1]} == {"whisper-tiny", "parakeet-0.6b"}
    assert {m.id for m in mock_config_entry.runtime_data.models} == {
        "whisper-tiny",
        "parakeet-0.6b",
    }


@pytest.mark.asyncio
async def test_event_handler_removes_stale_device(mock_hass, mock_config_entry):
    """When a model disappears, its device is removed on the next event."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(
        return_value=[_make_model("whisper-tiny"), _make_model("parakeet-0.6b")]
    )

    stale = MagicMock()
    stale.id = "device_parakeet"
    stale.identifiers = {("cortex_stt", "test_entry_123_parakeet-0.6b")}
    kept = MagicMock()
    kept.id = "device_tiny"
    kept.identifiers = {("cortex_stt", "test_entry_123_whisper-tiny")}

    mock_device_reg = MagicMock()
    dr.async_get = MagicMock(return_value=mock_device_reg)
    dr.async_entries_for_config_entry = MagicMock(return_value=[stale, kept])

    p1, p2 = _patched_setup(mock_client)
    with p1, p2:
        await async_setup_entry(mock_hass, mock_config_entry)
    handler = mock_hass.bus.async_listen.call_args.args[1]

    # parakeet got deleted on the addon; only whisper-tiny remains.
    mock_client.list_models = AsyncMock(return_value=[_make_model("whisper-tiny")])
    await handler(MagicMock())

    mock_device_reg.async_remove_device.assert_called_once_with("device_parakeet")


@pytest.mark.asyncio
async def test_event_handler_ignores_refresh_error(mock_hass, mock_config_entry):
    """A failed model refresh in the handler is swallowed (next event reconciles)."""
    import aiohttp

    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(return_value=[_make_model("whisper-tiny")])

    handler = await _setup_and_get_handler(mock_hass, mock_config_entry, mock_client)
    mock_client.list_models = AsyncMock(side_effect=aiohttp.ClientError())

    # Must not raise.
    await handler(MagicMock())


# ── platform dynamic add ──


@pytest.mark.asyncio
async def test_stt_platform_adds_new_model_live(mock_hass, mock_config_entry):
    """STT platform adds an entity only for newly-discovered models, and re-adds
    a model that was removed then downloaded again (known-set pruning)."""
    mock_config_entry.runtime_data = CortexSTTRuntimeData(
        client=MagicMock(), models=[_make_model("whisper-tiny")]
    )

    added: list = []

    def _add(entities):
        added.extend(entities)

    await stt_setup_entry(mock_hass, mock_config_entry, _add)
    assert {e._model.id for e in added} == {"whisper-tiny"}

    signal = models_changed_signal(mock_config_entry.entry_id)

    # A new model appears: only it is added (tiny is already known).
    async_dispatcher_send(
        mock_hass, signal, [_make_model("whisper-tiny"), _make_model("parakeet-0.6b")]
    )
    assert {e._model.id for e in added} == {"whisper-tiny", "parakeet-0.6b"}

    # parakeet is deleted: nothing added, but it leaves the known-set.
    async_dispatcher_send(mock_hass, signal, [_make_model("whisper-tiny")])
    assert len(added) == 2

    # parakeet re-downloaded: it is added again.
    async_dispatcher_send(
        mock_hass, signal, [_make_model("whisper-tiny"), _make_model("parakeet-0.6b")]
    )
    assert len(added) == 3
    assert [e._model.id for e in added].count("parakeet-0.6b") == 2
