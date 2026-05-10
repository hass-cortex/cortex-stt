"""Test fixtures for cortex-stt.

Mocks the homeassistant module hierarchy so that custom_components
can be imported without real dependencies.
"""

import sys
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# ── Mock homeassistant module hierarchy ──
_ha = ModuleType("homeassistant")
_ha_core = ModuleType("homeassistant.core")
_ha_config_entries = ModuleType("homeassistant.config_entries")
_ha_helpers = ModuleType("homeassistant.helpers")
_ha_helpers_cv = ModuleType("homeassistant.helpers.config_validation")
_ha_helpers_cv.config_entry_only_config_schema = lambda domain: {}
_ha_helpers_dr = ModuleType("homeassistant.helpers.device_registry")
_ha_helpers_ep = ModuleType("homeassistant.helpers.entity_platform")
_ha_helpers_aiohttp = ModuleType("homeassistant.helpers.aiohttp_client")
_ha_helpers_typing = ModuleType("homeassistant.helpers.typing")
_ha_helpers_typing.ConfigType = dict
_ha_components = ModuleType("homeassistant.components")

# ── Exceptions ──
_ha_exceptions = ModuleType("homeassistant.exceptions")


class _HomeAssistantError(Exception):
    """Base HA error that records translation metadata for test assertions."""

    def __init__(
        self,
        message: str = "",
        *,
        translation_domain: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


_ha_exceptions.HomeAssistantError = _HomeAssistantError
_ha_exceptions.ConfigEntryAuthFailed = type(
    "ConfigEntryAuthFailed", (_HomeAssistantError,), {}
)
_ha_exceptions.ConfigEntryNotReady = type(
    "ConfigEntryNotReady", (_HomeAssistantError,), {}
)

# ── Core ──
_ha_core.HomeAssistant = MagicMock
_ha_core.callback = lambda f: f

# ── ConfigEntry / ConfigEntryNotReady ──
_ha_config_entries.ConfigEntry = MagicMock
_ha_config_entries.ConfigEntryNotReady = _ha_exceptions.ConfigEntryNotReady


class _MockConfigFlow:
    """Mock ConfigFlow base class."""

    VERSION = 1
    hass = None
    _unique_id = None

    def __init__(self):
        self.context = {}

    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self, updates=None):
        pass

    def _async_current_entries(self, include_ignore=False):
        return []

    def _get_reauth_entry(self):
        return self._reauth_entry

    def async_update_reload_and_abort(self, entry, **kwargs):
        return {"type": "abort", "reason": "reauth_successful", **kwargs}


class _MockOptionsFlow:
    """Mock OptionsFlow base class."""

    hass = None
    config_entry = None

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


_ha_config_entries.ConfigFlow = _MockConfigFlow
_ha_config_entries.ConfigFlowResult = dict
_ha_config_entries.OptionsFlow = _MockOptionsFlow

# ── Device registry ──
_ha_helpers_dr.async_get = MagicMock()
_ha_helpers_dr.async_entries_for_config_entry = MagicMock(return_value=[])
_ha_helpers_dr.DeviceInfo = dict
_ha_helpers_dr.DeviceEntryType = MagicMock()
_ha_helpers_dr.DeviceEntryType.SERVICE = "service"

# ── Entity platform ──
_ha_helpers_ep.AddConfigEntryEntitiesCallback = MagicMock

# ── aiohttp_client ──
_ha_helpers_aiohttp.async_get_clientsession = MagicMock()

# ── service_info (hassio discovery) ──
_ha_helpers_si = ModuleType("homeassistant.helpers.service_info")
_ha_helpers_si_hassio = ModuleType("homeassistant.helpers.service_info.hassio")


@dataclass(frozen=True)
class _HassioServiceInfo:
    config: dict[str, Any]
    name: str
    slug: str
    uuid: str


_ha_helpers_si_hassio.HassioServiceInfo = _HassioServiceInfo

# ── Constants ──
_ha_const = ModuleType("homeassistant.const")


class _EntityCategory(StrEnum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


_ha_const.EntityCategory = _EntityCategory
_ha_const.Platform = MagicMock()
_ha_const.UnitOfInformation = MagicMock()
_ha_const.UnitOfInformation.BYTES = "B"
_ha_const.UnitOfTime = MagicMock()
_ha_const.UnitOfTime.MILLISECONDS = "ms"
_ha_const.UnitOfTime.SECONDS = "s"
_ha_const.UnitOfTime.MINUTES = "min"

# ── STT platform mocks ──
_ha_components_stt = ModuleType("homeassistant.components.stt")
_ha_components_stt.AudioFormats = MagicMock()
_ha_components_stt.AudioFormats.WAV = "wav"
_ha_components_stt.AudioCodecs = MagicMock()
_ha_components_stt.AudioCodecs.PCM = "pcm"
_ha_components_stt.AudioBitRates = MagicMock()
_ha_components_stt.AudioBitRates.BITRATE_16 = 16
_ha_components_stt.AudioSampleRates = MagicMock()
_ha_components_stt.AudioSampleRates.SAMPLERATE_16000 = 16000
_ha_components_stt.AudioChannels = MagicMock()
_ha_components_stt.AudioChannels.CHANNEL_MONO = 1
_ha_components_stt.SpeechMetadata = MagicMock


class _SpeechResult:
    """Real SpeechResult so tests can inspect attributes."""

    def __init__(self, text=None, result=None):
        self.text = text
        self.result = result


_ha_components_stt.SpeechResult = _SpeechResult
_ha_components_stt.SpeechResultState = MagicMock()
_ha_components_stt.SpeechResultState.SUCCESS = "success"
_ha_components_stt.SpeechResultState.ERROR = "error"
_ha_components_stt.SpeechToTextEntity = type(
    "SpeechToTextEntity",
    (),
    {"_attr_available": True, "async_write_ha_state": lambda self: None},
)

# ── Sensor platform mocks ──
_ha_components_sensor = ModuleType("homeassistant.components.sensor")


class _SensorStateClass(StrEnum):
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class _SensorDeviceClass(StrEnum):
    ENUM = "enum"


@dataclass(frozen=True, kw_only=True)
class _SensorEntityDescription:
    key: str = ""
    translation_key: str | None = None
    name: str | None = None
    icon: str | None = None
    native_unit_of_measurement: str | None = None
    suggested_display_precision: int | None = None
    state_class: _SensorStateClass | None = None
    entity_category: _EntityCategory | None = None
    entity_registry_enabled_default: bool = True
    device_class: _SensorDeviceClass | None = None
    options: list[str] | None = None


class _RestoreSensor:
    """Mock RestoreSensor base class."""

    _attr_native_value: Any = None
    _attr_should_poll: bool = True
    _attr_unique_id: str | None = None
    _attr_device_info: Any = None
    has_entity_name: bool = False
    entity_description: Any = None

    async def async_added_to_hass(self) -> None:
        pass

    async def async_will_remove_from_hass(self) -> None:
        pass

    async def async_get_last_sensor_data(self) -> Any:
        return None

    def async_write_ha_state(self) -> None:
        pass


_ha_components_sensor.RestoreSensor = _RestoreSensor
_ha_components_sensor.SensorEntityDescription = _SensorEntityDescription
_ha_components_sensor.SensorDeviceClass = _SensorDeviceClass
_ha_components_sensor.SensorStateClass = _SensorStateClass

# ── Diagnostics platform mocks ──
_ha_components_diagnostics = ModuleType("homeassistant.components.diagnostics")


def _redact(data: dict[str, Any], to_redact: set[str]) -> dict[str, Any]:
    """Minimal stand-in for homeassistant.components.diagnostics.async_redact_data."""
    return {k: "**REDACTED**" if k in to_redact else v for k, v in data.items()}


_ha_components_diagnostics.async_redact_data = _redact

# ── Binary sensor platform mocks ──
_ha_components_binary_sensor = ModuleType("homeassistant.components.binary_sensor")


class _BinarySensorDeviceClass(StrEnum):
    RUNNING = "running"


class _BinarySensorEntity:
    """Mock BinarySensorEntity base class."""

    _attr_unique_id: str | None = None
    _attr_device_info: Any = None
    _attr_translation_key: str | None = None
    _attr_device_class: Any = None
    _attr_entity_category: Any = None
    has_entity_name: bool = False

    def async_write_ha_state(self) -> None:
        pass


_ha_components_binary_sensor.BinarySensorDeviceClass = _BinarySensorDeviceClass
_ha_components_binary_sensor.BinarySensorEntity = _BinarySensorEntity

# ── Update coordinator mocks ──
_ha_helpers_uc = ModuleType("homeassistant.helpers.update_coordinator")


class _MockUpdateFailedError(_HomeAssistantError):
    """Mock UpdateFailed exception."""


class _MockDataUpdateCoordinator:
    """Mock DataUpdateCoordinator base class."""

    data: Any = None

    def __init__(self, hass, logger, *, name="", update_interval=None, **kwargs):
        self.hass = hass
        self.name = name
        self.update_interval = update_interval

    def __class_getitem__(cls, item):
        return cls

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def _async_update_data(self):
        raise NotImplementedError


class _MockCoordinatorEntity:
    """Mock CoordinatorEntity base class."""

    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls

    def async_write_ha_state(self) -> None:
        pass


_ha_helpers_uc.DataUpdateCoordinator = _MockDataUpdateCoordinator
_ha_helpers_uc.CoordinatorEntity = _MockCoordinatorEntity
_ha_helpers_uc.UpdateFailed = _MockUpdateFailedError

# ── Register all mocked modules ──
for mod_name, mod in [
    ("homeassistant", _ha),
    ("homeassistant.core", _ha_core),
    ("homeassistant.config_entries", _ha_config_entries),
    ("homeassistant.helpers", _ha_helpers),
    ("homeassistant.helpers.config_validation", _ha_helpers_cv),
    ("homeassistant.helpers.device_registry", _ha_helpers_dr),
    ("homeassistant.helpers.entity_platform", _ha_helpers_ep),
    ("homeassistant.helpers.aiohttp_client", _ha_helpers_aiohttp),
    ("homeassistant.helpers.service_info", _ha_helpers_si),
    ("homeassistant.helpers.service_info.hassio", _ha_helpers_si_hassio),
    ("homeassistant.helpers.typing", _ha_helpers_typing),
    ("homeassistant.helpers.update_coordinator", _ha_helpers_uc),
    ("homeassistant.exceptions", _ha_exceptions),
    ("homeassistant.const", _ha_const),
    ("homeassistant.components", _ha_components),
    ("homeassistant.components.stt", _ha_components_stt),
    ("homeassistant.components.sensor", _ha_components_sensor),
    ("homeassistant.components.binary_sensor", _ha_components_binary_sensor),
    ("homeassistant.components.diagnostics", _ha_components_diagnostics),
]:
    sys.modules[mod_name] = mod

# Also mock voluptuous since config_flow uses it
try:
    import voluptuous  # noqa: F401
except ImportError:
    _vol = MagicMock()
    sys.modules["voluptuous"] = _vol

import pytest  # noqa: E402


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry for cortex-stt."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.data = {
        "host": "http://localhost:8769",
        "api_key": "test-api-key",
    }
    entry.runtime_data = None
    return entry


def make_model(**overrides):
    """Create a ModelInfo with sensible defaults."""
    from custom_components.cortex_stt.models import ModelInfo

    defaults = {
        "id": "whisper-small",
        "name": "Whisper Small",
        "description": "A small model",
        "engine_type": "whisper",
        "status": "downloaded",
        "size_mb": 500,
        "supported_languages": ["en", "zh"],
    }
    defaults.update(overrides)
    return ModelInfo(**defaults)
