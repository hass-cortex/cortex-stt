"""Shared helper for live, event-driven model entity setup.

Each platform builds entities for the models present at setup, then keeps
listening: when the addon fires a models-changed event (see the ``__init__``
event-bus handler), the dispatcher signal fires and any newly-downloaded model
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
from .models import ModelInfo

if TYPE_CHECKING:
    from . import CortexSTTConfigEntry


@callback
def async_setup_dynamic_models(
    hass: HomeAssistant,
    config_entry: CortexSTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build_entities: Callable[[ModelInfo], Iterable[Entity]],
) -> None:
    """Add entities for current models and any added later via an event.

    Args:
        hass: Home Assistant instance.
        config_entry: The Cortex STT config entry.
        async_add_entities: Platform callback to register new entities.
        build_entities: Builds this platform's entities for a single model.
    """
    known: set[str] = set()

    @callback
    def _sync(models: list[ModelInfo]) -> None:
        # Prune ids whose models are gone so a deleted-then-re-added model is
        # picked up again; then add entities for any not-yet-known model.
        known.intersection_update({m.id for m in models})
        new = [m for m in models if m.id not in known]
        if not new:
            return
        # Build + add first, then mark known: if construction/registration
        # raises, the model is NOT recorded as known and is retried on the
        # next event rather than being stranded.
        entities = [entity for model in new for entity in build_entities(model)]
        async_add_entities(entities)
        known.update(m.id for m in new)

    _sync(config_entry.runtime_data.models)
    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, models_changed_signal(config_entry.entry_id), _sync
        )
    )
