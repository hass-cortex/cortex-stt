"""Tests for Cortex STT config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.cortex_stt.config_flow import (
    CortexSTTConfigFlow,
    CortexSTTOptionsFlow,
)
from custom_components.cortex_stt.const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)

USER_INPUT = {
    "host": "http://localhost:8769",
    "api_key": "test-api-key",
}


def _make_hassio_discovery(
    host: str = "local-cortex-stt",
    port: int = 8769,
    api_key: str = "discovered-api-key",
    name: str = "Cortex STT",
    slug: str = "local_cortex_stt",
    uuid: str = "abcd1234",
) -> HassioServiceInfo:
    """Build a HassioServiceInfo payload mimicking the addon discovery."""
    return HassioServiceInfo(
        config={"host": host, "port": port, "api_key": api_key},
        name=name,
        slug=slug,
        uuid=uuid,
    )


def _make_flow() -> CortexSTTConfigFlow:
    """Create a CortexSTTConfigFlow with a mock hass."""
    flow = CortexSTTConfigFlow()
    flow.hass = MagicMock()
    return flow


# ── async_step_user ──


@pytest.mark.asyncio
async def test_step_user_shows_form():
    """Show form when called with no user_input."""
    flow = _make_flow()
    result = await flow.async_step_user(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_step_user_success():
    """Create entry on successful validation with version in title."""
    flow = _make_flow()
    mock_client = MagicMock()
    mock_client.health = AsyncMock(return_value={"version": "1.2.3"})

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (None, mock_client)
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"] == "create_entry"
    assert result["title"] == "Cortex STT (1.2.3)"
    assert result["data"] == USER_INPUT


@pytest.mark.asyncio
async def test_step_user_validation_error():
    """Show error when _validate_input returns cannot_connect."""
    flow = _make_flow()
    mock_client = MagicMock()

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = ("cannot_connect", mock_client)
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_step_user_invalid_api_key():
    """Show error when _validate_input returns invalid_api_key."""
    flow = _make_flow()
    mock_client = MagicMock()

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = ("invalid_api_key", mock_client)
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_api_key"}


@pytest.mark.asyncio
async def test_step_user_health_exception_fallback_title():
    """Use fallback title when client.health() raises."""
    flow = _make_flow()
    mock_client = MagicMock()
    mock_client.health = AsyncMock(side_effect=aiohttp.ClientError("timeout"))

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (None, mock_client)
        result = await flow.async_step_user(user_input=USER_INPUT)

    assert result["type"] == "create_entry"
    assert result["title"] == "Cortex STT"


@pytest.mark.asyncio
async def test_step_user_duplicate_server():
    """Abort when unique ID is already configured."""
    flow = _make_flow()
    mock_client = MagicMock()
    mock_client.health = AsyncMock(return_value={"version": "1.0.0"})

    # Make _abort_if_unique_id_configured raise to simulate duplicate

    class _AbortError(Exception):
        def __init__(self, reason):
            self.reason = reason
            super().__init__(reason)

    with (
        patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate,
        patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=_AbortError("already_configured"),
        ),
    ):
        mock_validate.return_value = (None, mock_client)
        with pytest.raises(_AbortError, match="already_configured"):
            await flow.async_step_user(user_input=USER_INPUT)


# ── async_step_hassio ──


@pytest.mark.asyncio
async def test_step_hassio_shows_confirm_form():
    """First-time Supervisor discovery shows the confirm form."""
    flow = _make_flow()
    discovery = _make_hassio_discovery()

    with patch.object(flow, "_abort_if_unique_id_configured"):
        result = await flow.async_step_hassio(discovery)

    assert result["type"] == "form"
    assert result["step_id"] == "hassio_confirm"


@pytest.mark.asyncio
async def test_step_hassio_confirm_success():
    """Confirming discovery creates the entry with host/api_key from payload."""
    flow = _make_flow()
    discovery = _make_hassio_discovery(
        host="local-cortex-stt", port=8769, api_key="sk-discovered"
    )
    flow._hassio_discovery = discovery

    mock_client = MagicMock()
    mock_client.health = AsyncMock(return_value={"version": "1.2.3"})

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (None, mock_client)
        result = await flow.async_step_hassio_confirm(user_input={})

    assert result["type"] == "create_entry"
    assert result["title"] == "Cortex STT (1.2.3)"
    assert result["data"] == {
        "host": "http://local-cortex-stt:8769",
        "api_key": "sk-discovered",
    }
    mock_validate.assert_called_once_with(
        "http://local-cortex-stt:8769", "sk-discovered"
    )


@pytest.mark.asyncio
async def test_step_hassio_confirm_cannot_connect():
    """Validation failure on confirm keeps the form with an error."""
    flow = _make_flow()
    flow._hassio_discovery = _make_hassio_discovery()
    mock_client = MagicMock()

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = ("cannot_connect", mock_client)
        result = await flow.async_step_hassio_confirm(user_input={})

    assert result["type"] == "form"
    assert result["step_id"] == "hassio_confirm"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_step_hassio_already_configured():
    """Supervisor discovery aborts when unique_id already configured."""
    flow = _make_flow()
    discovery = _make_hassio_discovery()

    class _AbortError(Exception):
        def __init__(self, reason):
            self.reason = reason
            super().__init__(reason)

    with (
        patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=_AbortError("already_configured"),
        ),
        pytest.raises(_AbortError, match="already_configured"),
    ):
        await flow.async_step_hassio(discovery)


@pytest.mark.asyncio
async def test_step_hassio_passes_updates_for_rotation():
    """When admin rotates ha_api_key, discovery passes updates= so the
    existing entry gets its host/api_key refreshed without manual reauth.
    """
    flow = _make_flow()
    discovery = _make_hassio_discovery(
        host="local-cortex-stt", port=8769, api_key="rotated-key"
    )

    with patch.object(flow, "_abort_if_unique_id_configured") as mock_abort:
        await flow.async_step_hassio(discovery)

    mock_abort.assert_called_once_with(
        updates={
            "host": "http://local-cortex-stt:8769",
            "api_key": "rotated-key",
        }
    )


# ── async_step_reauth ──


@pytest.mark.asyncio
async def test_step_reauth_delegates():
    """Verify reauth delegates to reauth_confirm and shows form."""
    flow = _make_flow()
    flow._reauth_entry = MagicMock()
    flow._reauth_entry.data = {"host": "http://localhost:8769", "api_key": "old-key"}

    result = await flow.async_step_reauth(entry_data={})
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


# ── async_step_reauth_confirm ──


@pytest.mark.asyncio
async def test_step_reauth_confirm_shows_form():
    """Show form when called with no user_input."""
    flow = _make_flow()
    flow._reauth_entry = MagicMock()
    flow._reauth_entry.data = {"host": "http://localhost:8769", "api_key": "old-key"}

    result = await flow.async_step_reauth_confirm(user_input=None)
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


@pytest.mark.asyncio
async def test_step_reauth_confirm_success():
    """Update entry on successful reauth validation."""
    flow = _make_flow()
    reauth_entry = MagicMock()
    reauth_entry.data = {"host": "http://localhost:8769", "api_key": "old-key"}
    flow._reauth_entry = reauth_entry

    mock_client = MagicMock()

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = (None, mock_client)
        result = await flow.async_step_reauth_confirm(
            user_input={"api_key": "new-api-key"}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert result["data_updates"] == {"api_key": "new-api-key"}

    # Validate that _validate_input was called with original host and new key
    mock_validate.assert_called_once_with("http://localhost:8769", "new-api-key")


@pytest.mark.asyncio
async def test_step_reauth_confirm_error():
    """Show error when reauth validation fails."""
    flow = _make_flow()
    reauth_entry = MagicMock()
    reauth_entry.data = {"host": "http://localhost:8769", "api_key": "old-key"}
    flow._reauth_entry = reauth_entry

    mock_client = MagicMock()

    with patch.object(flow, "_validate_input", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = ("cannot_connect", mock_client)
        result = await flow.async_step_reauth_confirm(user_input={"api_key": "bad-key"})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}


# ── options flow ──


def _make_options_flow(current: int | None = None) -> CortexSTTOptionsFlow:
    """Create a CortexSTTOptionsFlow with a mock config entry."""
    flow = CortexSTTOptionsFlow()
    entry = MagicMock()
    entry.options = {CONF_UPDATE_INTERVAL: current} if current is not None else {}
    flow.hass = MagicMock()
    flow.config_entry = entry
    return flow


@pytest.mark.asyncio
async def test_options_flow_shows_form_with_default():
    """Form uses default when no prior option was stored."""
    flow = _make_options_flow()
    result = await flow.async_step_init(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_shows_form_with_existing_value():
    """Form uses the previously-stored value as default."""
    flow = _make_options_flow(current=60)
    result = await flow.async_step_init(user_input=None)

    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_options_flow_saves_value():
    """Submitting the form creates the options entry."""
    flow = _make_options_flow()
    result = await flow.async_step_init(user_input={CONF_UPDATE_INTERVAL: 45})

    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_UPDATE_INTERVAL: 45}


@pytest.mark.asyncio
async def test_options_flow_default_constant_available():
    """The DEFAULT_UPDATE_INTERVAL constant is exported for consumers."""
    assert isinstance(DEFAULT_UPDATE_INTERVAL, int)
    assert DEFAULT_UPDATE_INTERVAL > 0
