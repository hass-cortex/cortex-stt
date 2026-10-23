"""Shared helper for live, event-driven Variant entity setup.

Each platform builds entities for the Variants installed at setup, then keeps
listening: when the addon fires a models-changed event (see the ``__init__``
event-bus handler), the dispatcher signal fires and any newly-installed Variant
gets its entities added without a config-entry reload. Entity *removal* is
handled centrally by device removal in ``__init__``; this helper only adds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import models_changed_signal
from .models import Variant

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry


@callback
def async_setup_dynamic_models(
    hass: HomeAssistant,
    config_entry: CortexSTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build_entities: Callable[[Variant], Iterable[Entity]],
) -> None:
    """Add entities for current Variants and any installed later via an event.

    Args:
        hass: Home Assistant instance.
        config_entry: The Cortex STT config entry.
        async_add_entities: Platform callback to register new entities.
        build_entities: Builds this platform's entities for a single Variant.
    """
    known: set[str] = set()

    @callback
    def _sync(variants: list[Variant]) -> None:
        # Prune keys whose Variants are gone so a deleted-then-re-added one is
        # picked up again; then add entities for any not-yet-known Variant.
        known.intersection_update({v.key for v in variants})
        new = [v for v in variants if v.key not in known]
        if not new:
            return
        # Build + add first, then mark known: if construction/registration
        # raises, the Variant is NOT recorded as known and is retried on the
        # next event rather than being stranded.
        entities = [entity for variant in new for entity in build_entities(variant)]
        async_add_entities(entities)
        known.update(v.key for v in new)

    _sync(config_entry.runtime_data.variants)
    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, models_changed_signal(config_entry.entry_id), _sync
        )
    )
