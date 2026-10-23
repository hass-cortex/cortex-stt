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
from custom_components.cortex_stt.models import (
    CortexSTTRuntimeData,
    ModelInfo,
    Variant,
    VariantInfo,
    installed_variants,
)
from custom_components.cortex_stt.stt import async_setup_entry as stt_setup_entry


def _make_model(model_id: str, quants: tuple[str, ...] = ("Q8_0",)) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        description="test model",
        status="downloaded" if quants else "available",
        size_mb=100,
        languages=["en"],
        preferred_quant=quants[0] if quants else None,
        variants=[VariantInfo(quant=q, status="downloaded") for q in quants],
    )


def _variants(*models: ModelInfo) -> list[Variant]:
    return installed_variants(list(models))


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

    received: list[list[Variant]] = []
    async_dispatcher_connect(
        mock_hass,
        models_changed_signal(mock_config_entry.entry_id),
        received.append,
    )

    handler = await _setup_and_get_handler(mock_hass, mock_config_entry, mock_client)

    # Addon now reports a second quant of whisper-tiny, another model, and
    # one with nothing installed.
    mock_client.list_models = AsyncMock(
        return_value=[
            _make_model("whisper-tiny", ("Q8_0", "Q4_K_M")),
            _make_model("parakeet-tdt-0.6b-v3"),
            _make_model("sensevoice", ()),
        ]
    )
    await handler(MagicMock())

    expected = {"whisper-tiny:Q8_0", "whisper-tiny:Q4_K_M", "parakeet-tdt-0.6b-v3:Q8_0"}
    assert received, "dispatcher signal was not sent"
    assert {v.key for v in received[-1]} == expected
    assert {v.key for v in mock_config_entry.runtime_data.variants} == expected


@pytest.mark.asyncio
async def test_event_handler_removes_stale_device(mock_hass, mock_config_entry):
    """When one quant is uninstalled, only its device goes on the next event."""
    mock_client = MagicMock()
    mock_client.validate = AsyncMock(return_value=None)
    mock_client.list_models = AsyncMock(
        return_value=[_make_model("whisper-tiny", ("Q8_0", "Q4_K_M"))]
    )

    stale = MagicMock()
    stale.id = "device_tiny_q4"
    stale.identifiers = {("cortex_stt", "test_entry_123_whisper-tiny:Q4_K_M")}
    kept = MagicMock()
    kept.id = "device_tiny_q8"
    kept.identifiers = {("cortex_stt", "test_entry_123_whisper-tiny:Q8_0")}

    mock_device_reg = MagicMock()
    dr.async_get = MagicMock(return_value=mock_device_reg)
    dr.async_entries_for_config_entry = MagicMock(return_value=[stale, kept])

    p1, p2 = _patched_setup(mock_client)
    with p1, p2:
        await async_setup_entry(mock_hass, mock_config_entry)
    handler = mock_hass.bus.async_listen.call_args.args[1]

    # Q4_K_M was uninstalled on the addon; Q8_0 keeps serving.
    mock_client.list_models = AsyncMock(return_value=[_make_model("whisper-tiny")])
    await handler(MagicMock())

    mock_device_reg.async_remove_device.assert_called_once_with("device_tiny_q4")


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
    """STT platform adds an entity only for newly-installed Variants, and re-adds
    one that was removed then installed again (known-set pruning)."""
    one = _variants(_make_model("whisper-tiny"))
    two = _variants(_make_model("whisper-tiny", ("Q8_0", "Q4_K_M")))
    mock_config_entry.runtime_data = CortexSTTRuntimeData(
        client=MagicMock(), variants=one
    )

    added: list = []

    def _add(entities):
        added.extend(entities)

    await stt_setup_entry(mock_hass, mock_config_entry, _add)
    assert [e._variant.key for e in added] == ["whisper-tiny:Q8_0"]

    signal = models_changed_signal(mock_config_entry.entry_id)

    # A second quant is installed: only it is added (Q8_0 is already known).
    async_dispatcher_send(mock_hass, signal, two)
    assert [e._variant.key for e in added] == [
        "whisper-tiny:Q8_0",
        "whisper-tiny:Q4_K_M",
    ]

    # Q4_K_M is uninstalled: nothing added, but it leaves the known-set.
    async_dispatcher_send(mock_hass, signal, one)
    assert len(added) == 2

    # Q4_K_M installed again: it is added again.
    async_dispatcher_send(mock_hass, signal, two)
    assert [e._variant.key for e in added].count("whisper-tiny:Q4_K_M") == 2
