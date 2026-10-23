"""Tests for moving pre-Variant devices and entities onto Variants."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er

from custom_components.cortex_stt.migration import (
    async_migrate_to_variants,
    plan_variant_migration,
)
from custom_components.cortex_stt.models import ModelInfo, VariantInfo

ENTRY = "e1"
SUFFIXES = ["", "_loaded", "_total_requests"]


def _model(
    model_id: str, quants: tuple[str | None, ...], preferred: str | None = None
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        description="",
        status="downloaded",
        size_mb=0,
        languages=[],
        preferred_quant=preferred,
        variants=[VariantInfo(quant=q, status="downloaded") for q in quants],
    )


# ── plan ──


def test_a_model_moves_onto_the_quant_it_has_installed():
    plan = plan_variant_migration(ENTRY, [_model("whisper-small", ("Q8_0",))], SUFFIXES)

    assert plan.devices == {"e1_whisper-small": "e1_whisper-small:Q8_0"}
    assert plan.entities["cortex_stt_e1_whisper-small"] == (
        "cortex_stt_e1_whisper-small:Q8_0"
    )
    assert plan.entities["cortex_stt_e1_whisper-small_loaded"] == (
        "cortex_stt_e1_whisper-small:Q8_0_loaded"
    )


def test_with_several_quants_installed_the_preferred_one_inherits():
    model = _model("whisper-small", ("Q4_K_M", "Q8_0"), preferred="Q8_0")
    plan = plan_variant_migration(ENTRY, [model], SUFFIXES)

    assert plan.devices == {"e1_whisper-small": "e1_whisper-small:Q8_0"}


def test_a_custom_model_keeps_its_keys():
    plan = plan_variant_migration(ENTRY, [_model("my-custom", (None,))], SUFFIXES)

    assert plan.devices == {}
    assert plan.entities == {}


def test_one_model_id_prefixing_another_does_not_mix_them():
    """``parakeet-tdt`` prefixes ``parakeet-tdt_ctc-110m``; each keeps its own."""
    models = [
        _model("parakeet-tdt", ("Q8_0",)),
        _model("parakeet-tdt_ctc-110m", ("Q4_K_M",)),
    ]
    plan = plan_variant_migration(ENTRY, models, SUFFIXES)

    assert plan.entities["cortex_stt_e1_parakeet-tdt_ctc-110m_total_requests"] == (
        "cortex_stt_e1_parakeet-tdt_ctc-110m:Q4_K_M_total_requests"
    )
    assert plan.entities["cortex_stt_e1_parakeet-tdt_total_requests"] == (
        "cortex_stt_e1_parakeet-tdt:Q8_0_total_requests"
    )


# ── apply ──


@dataclass
class _Device:
    id: str
    identifiers: set[tuple[str, str]]


@dataclass
class _Entity:
    entity_id: str
    unique_id: str
    domain: str


class _DeviceRegistry:
    def __init__(self, devices: list[_Device]) -> None:
        self.devices = devices

    def async_update_device(self, device_id, new_identifiers):
        next(d for d in self.devices if d.id == device_id).identifiers = new_identifiers


class _EntityRegistry:
    def __init__(self, entities: list[_Entity]) -> None:
        self.entities = entities

    def async_get_entity_id(self, domain, platform, unique_id):
        return next(
            (
                e.entity_id
                for e in self.entities
                if e.domain == domain and e.unique_id == unique_id
            ),
            None,
        )

    def async_update_entity(self, entity_id, new_unique_id):
        next(
            e for e in self.entities if e.entity_id == entity_id
        ).unique_id = new_unique_id


def _apply(devices: _DeviceRegistry, entities: _EntityRegistry, models) -> None:
    dr.async_get = MagicMock(return_value=devices)
    dr.async_entries_for_config_entry = MagicMock(return_value=devices.devices)
    er.async_get = MagicMock(return_value=entities)
    er.async_entries_for_config_entry = MagicMock(return_value=entities.entities)
    entry = MagicMock()
    entry.entry_id = ENTRY
    async_migrate_to_variants(MagicMock(), entry, models, SUFFIXES)


def test_migration_keeps_entity_ids_and_moves_their_keys():
    devices = _DeviceRegistry([_Device("d1", {("cortex_stt", "e1_whisper-small")})])
    stt = _Entity("stt.whisper_small", "cortex_stt_e1_whisper-small", "stt")
    loaded = _Entity(
        "binary_sensor.whisper_small_loaded",
        "cortex_stt_e1_whisper-small_loaded",
        "binary_sensor",
    )
    entities = _EntityRegistry([stt, loaded])
    models = [_model("whisper-small", ("Q8_0",))]

    _apply(devices, entities, models)

    assert devices.devices[0].identifiers == {("cortex_stt", "e1_whisper-small:Q8_0")}
    assert stt.entity_id == "stt.whisper_small"
    assert stt.unique_id == "cortex_stt_e1_whisper-small:Q8_0"
    assert loaded.unique_id == "cortex_stt_e1_whisper-small:Q8_0_loaded"

    # A second run (every later start) finds nothing under the old keys.
    _apply(devices, entities, models)
    assert stt.unique_id == "cortex_stt_e1_whisper-small:Q8_0"


def test_migration_never_takes_over_a_key_already_in_use():
    """If the Variant's entity already exists, the old one is left alone."""
    old = _Entity("stt.whisper_small", "cortex_stt_e1_whisper-small", "stt")
    new = _Entity("stt.whisper_small_q8_0", "cortex_stt_e1_whisper-small:Q8_0", "stt")
    entities = _EntityRegistry([old, new])
    devices = _DeviceRegistry(
        [
            _Device("d1", {("cortex_stt", "e1_whisper-small")}),
            _Device("d2", {("cortex_stt", "e1_whisper-small:Q8_0")}),
        ]
    )

    _apply(devices, entities, [_model("whisper-small", ("Q8_0",))])

    assert old.unique_id == "cortex_stt_e1_whisper-small"
    assert devices.devices[0].identifiers == {("cortex_stt", "e1_whisper-small")}
