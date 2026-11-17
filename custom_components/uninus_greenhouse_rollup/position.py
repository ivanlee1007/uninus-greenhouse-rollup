"""Read-only projections of an entry-owned Cover's published estimate.

Never restore independently, integrate time, or invoke actuator methods here.
The Cover remains the only estimator and restore authority.
"""
from math import isfinite

from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class PositionEntity(Entity):
    """Subscribe to publication by exact registry ownership, not a guessed name."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager, key):
        self.manager = manager
        self._source_entity_id = None
        self._attr_unique_id = f'{manager.entry.entry_id}:{key}'
        self._attr_translation_key = key
        self._attr_device_info = manager.cover.device_info

    def _source_state(self):
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id('cover', DOMAIN, self.manager.entry.entry_id)
        row = registry.async_get(entity_id) if entity_id else None
        cover = self.manager.cover
        if (row is None or row.disabled or row.config_entry_id != self.manager.entry.entry_id
                or self.manager.closing or cover._removing
                or entity_id != cover.entity_id or not cover.available):
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            return None
        return state

    @property
    def available(self):
        return self._source_state() is not None

    @property
    def estimated_position(self):
        state = self._source_state()
        value = state.attributes.get('current_position') if state is not None else None
        # Do not turn unknown/invalid estimates into calibrated zero.
        return value if type(value) in (int, float) and isfinite(value) and 0 <= value <= 100 else None

    @property
    def extra_state_attributes(self):
        state = self._source_state()
        attributes = state.attributes if state is not None else {}
        return {
            'source_cover': er.async_get(self.hass).async_get_entity_id(
                'cover', DOMAIN, self.manager.entry.entry_id),
            'position_is_estimated': True,
            'position_unverified': True,
            'physical_arrival_confirmed': False,
            'position_basis': attributes.get('position_basis', 'unknown'),
            'position_confidence': attributes.get('position_confidence', 'unknown'),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._source_entity_id = er.async_get(self.hass).async_get_entity_id(
            'cover', DOMAIN, self.manager.entry.entry_id)
        self.async_on_remove(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._source_changed))

    @callback
    def _source_changed(self, event):
        current = er.async_get(self.hass).async_get_entity_id(
            'cover', DOMAIN, self.manager.entry.entry_id)
        if event.data['entity_id'] in (current, self._source_entity_id):
            self._source_entity_id = current
            self.async_write_ha_state()
