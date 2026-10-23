"""Move per-model devices and entities onto Variants (app ADR 0007).

Before Variants, a model's device and entities were keyed by the model id.
Each is now keyed by a Variant (``model:quant``). On upgrade every model has
the quant it was serving installed, so its device and entities are rewritten
in place to that Variant: entity ids -- and the Assist pipelines and
stt-corrector references that name them -- survive. A Custom model has no
quant, so its keys never change.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .models import ModelInfo, variant_key

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class VariantMigration:
    """Old identifier -> new identifier, for devices and entity unique ids."""

    devices: dict[str, str] = field(default_factory=dict)
    entities: dict[str, str] = field(default_factory=dict)


def plan_variant_migration(
    entry_id: str,
    models: Iterable[ModelInfo],
    entity_suffixes: Iterable[str],
) -> VariantMigration:
    """Plan the rewrite of each model's keys to its Preferred variant's.

    Args:
        entry_id: The config entry the devices and entities belong to.
        models: Models from GET /api/models.
        entity_suffixes: What follows the model id in each entity's unique id
            (``""`` for the STT entity, ``"_loaded"``, one per sensor).

    Returns:
        The exact old -> new identifiers. Old ones are matched whole, never by
        prefix: one model id can prefix another (``parakeet-tdt`` and
        ``parakeet-tdt_ctc-110m``).
    """
    plan = VariantMigration()
    suffixes = list(entity_suffixes)
    for model in models:
        installed = [v for v in model.variants if v.status == "downloaded" and v.quant]
        if not installed:
            continue
        target = next(
            (v for v in installed if v.quant == model.preferred_quant), installed[0]
        )
        new = variant_key(model.id, target.quant)
        plan.devices[f"{entry_id}_{model.id}"] = f"{entry_id}_{new}"
        for suffix in suffixes:
            old_uid = f"{DOMAIN}_{entry_id}_{model.id}{suffix}"
            plan.entities[old_uid] = f"{DOMAIN}_{entry_id}_{new}{suffix}"
    return plan


@callback
def async_migrate_to_variants(
    hass: HomeAssistant,
    entry: CortexSTTConfigEntry,
    models: list[ModelInfo],
    entity_suffixes: Iterable[str],
) -> None:
    """Rewrite pre-Variant devices and entities in place.

    Idempotent: an identifier already rewritten is no longer found under its
    old value, and a rewrite whose target already exists is skipped rather
    than merged.
    """
    plan = plan_variant_migration(entry.entry_id, models, entity_suffixes)

    # Looked up among this entry's devices: identifiers are only unique
    # within a config entry.
    device_reg = dr.async_get(hass)
    by_identifier = {
        identifier: device
        for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id)
        for domain, identifier in device.identifiers
        if domain == DOMAIN
    }
    for old, new in plan.devices.items():
        device = by_identifier.get(old)
        if device is None or new in by_identifier:
            continue
        device_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new)})
        _LOGGER.info("Moved device %s to variant %s", old, new)

    entity_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        new_uid = plan.entities.get(entity.unique_id)
        if new_uid is None:
            continue
        if entity_reg.async_get_entity_id(entity.domain, DOMAIN, new_uid):
            continue
        entity_reg.async_update_entity(entity.entity_id, new_unique_id=new_uid)
        _LOGGER.debug("Moved %s to unique id %s", entity.entity_id, new_uid)
